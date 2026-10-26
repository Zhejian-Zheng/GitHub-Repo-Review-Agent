-- Apply after 20261006_atomic_history.sql. Preserve unverified history across runs.
begin;
-- Coverage certificates are produced by the trusted scanner, not by model output.
create or replace function public.review_policy(p_report jsonb)
returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select jsonb_build_object(
    'ignore', coalesce(p_report #> '{metrics,policy_config,ignore}', '[]'),
    'disabled_rules', coalesce(p_report #> '{metrics,policy_config,disabled_rules}', '[]'),
    'disabled_categories', coalesce(p_report #> '{metrics,policy_config,disabled_categories}', '[]'),
    'severity_overrides', coalesce(p_report #> '{metrics,policy_config,severity_overrides}', '{}'));
$$;

create or replace function public.review_finding_rechecked(p_report jsonb, p_finding jsonb)
returns boolean language plpgsql immutable set search_path = public, pg_temp as $$
declare
  coverage jsonb := p_report #> '{metrics,review_coverage}';
  paths jsonb := coalesce(p_finding->'evidence_paths', '[]');
begin
  if review_policy(p_report) is distinct from p_finding #> '{resolution_context,policy}'
     or coverage->>'version' is distinct from '1' then return false; end if;
  if nullif(p_finding->>'path', '') is not null then
    paths := paths || jsonb_build_array(p_finding->>'path');
  end if;
  if jsonb_array_length(paths)>0
     and p_finding #>> '{resolution_context,evidence_was_present}' = 'true'
     and coverage->>'inventory_complete' = 'true'
     and not exists (select 1 from jsonb_array_elements_text(paths) path
                     where coalesce(coverage->'inventory_paths', '[]') ? path)
  then return true; end if;
  if p_finding->>'source' = 'ai' then return false; end if;
  if p_finding->>'rule_id' = 'dependency.osv' or p_finding->>'category' = 'dependency vulnerabilities'
  then return coalesce(coverage->>'inventory_complete' = 'true', false)
              and coalesce(p_report #>> '{metrics,vulnerability_scan,status}' in ('clean','findings'), false); end if;
  if p_finding->>'title' like 'Fix % Ruff %'
  then return coalesce(coverage->>'ruff_complete' = 'true', false); end if;
  return coalesce(coverage->>'rules_complete' = 'true', false);
end;
$$;
revoke all on function public.review_policy(jsonb) from public, anon, authenticated;
revoke all on function public.review_finding_rechecked(jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.review_policy(jsonb) to service_role;
grant execute on function public.review_finding_rechecked(jsonb,jsonb) to service_role;

create or replace function public.save_review_history(
    p_payload jsonb, p_operation uuid, p_job uuid default null,
    p_lease text default null, p_result jsonb default null
) returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_owner uuid := (p_payload->>'owner_id')::uuid;
    v_hash text := encode(sha256(convert_to(p_payload::text, 'UTF8')), 'hex');
    v_cached review_history_operations%rowtype;
    v_job review_jobs%rowtype;
    v_repository uuid;
    v_run uuid;
    v_previous uuid;
    v_previous_report jsonb;
    v_previous_findings jsonb;
    v_unverified jsonb;
    v_report jsonb := p_payload->'report';
    v_findings jsonb := p_payload->'report'->'findings';
    v_feedback jsonb;
    v_new jsonb;
    v_existing jsonb;
    v_resolved jsonb;
    v_score integer;
    v_result jsonb;
    v_ai jsonb := p_payload->'report'->'ai_review';
begin
    if p_operation is null or coalesce(p_payload->>'repo_url', '') = ''
       or jsonb_typeof(v_findings) is distinct from 'array'
       or jsonb_typeof(v_report) is distinct from 'object' then
        raise exception 'Invalid history transaction input';
    end if;
    if p_job is not null and (p_job <> p_operation or p_lease is null
       or jsonb_typeof(p_result) is distinct from 'object') then
        raise exception 'Invalid job completion input';
    end if;
    -- Order is operation -> job -> repository everywhere in this RPC.
    perform pg_advisory_xact_lock(hashtextextended('review-operation:' || p_operation::text, 0));
    select * into v_cached from review_history_operations where operation_id = p_operation;
    if found then
        if v_cached.owner_id is distinct from v_owner or v_cached.payload_hash <> v_hash
           or v_cached.job_id is distinct from p_job then
            raise exception 'History operation conflicts with an earlier request';
        end if;
        -- Exact retries after a lost response succeed, including expired leases.
        if p_job is not null and not exists (
            select 1 from review_jobs where id = p_job and owner_id is not distinct from v_owner
              and status = 'completed' and lease_token = p_lease
        ) then
            raise exception 'History operation is not owned by this worker';
        end if;
        return v_cached.result_json;
    end if;
    if p_job is not null then
        select * into v_job from review_jobs where id = p_job for update;
        if not found or v_job.owner_id is distinct from v_owner or v_job.status <> 'running'
           or v_job.lease_token is distinct from p_lease
           or v_job.lease_expires_at is null or v_job.lease_expires_at <= clock_timestamp() then
            raise exception 'Review job lease expired or ownership changed';
        end if;
    end if;
    perform pg_advisory_xact_lock(hashtextextended(
        'review-repository:' || coalesce(v_owner::text, 'anonymous') || ':' || (p_payload->>'repo_url'), 0));
    -- Partial unique indexes also protect against concurrent older clients.
    if v_owner is null then
        insert into repositories(repo_url, repo_name, default_branch)
        values(p_payload->>'repo_url', p_payload->>'repo_name', p_payload->>'branch')
        on conflict (repo_url) where owner_id is null do update
        set repo_name = excluded.repo_name, default_branch = excluded.default_branch
        returning id into v_repository;
    else
        insert into repositories(owner_id, repo_url, repo_name, default_branch)
        values(v_owner, p_payload->>'repo_url', p_payload->>'repo_name', p_payload->>'branch')
        on conflict (owner_id, repo_url) where owner_id is not null do update
        set repo_name = excluded.repo_name, default_branch = excluded.default_branch
        returning id into v_repository;
    end if;
    select id into v_previous from review_runs where repository_id = v_repository and status = 'completed'
      order by created_at desc, id desc limit 1;
    select coalesce(jsonb_agg(to_jsonb(f)), '[]') into v_feedback from finding_feedback f
      where f.repository_id = v_repository and f.owner_id = v_owner;
    select report_json into v_previous_report from review_runs where id = v_previous;
    -- Carry original policy and evidence presence through arbitrarily many partial runs.
    select coalesce(jsonb_agg(item), '[]') into v_previous_findings from (
      select distinct on (item->>'fingerprint') item from (
        select f || jsonb_build_object('resolution_context', jsonb_build_object(
          'policy', review_policy(v_previous_report),
          'evidence_was_present', not exists (
            select 1 from jsonb_array_elements_text(
              coalesce(f->'evidence_paths', '[]') ||
              case when nullif(f->>'path', '') is not null then jsonb_build_array(f->>'path') else '[]'::jsonb end
            ) path where not coalesce(v_previous_report #> '{metrics,review_coverage,inventory_paths}', '[]') ? path
          ))) as item, 1 as current_rank
        from jsonb_array_elements(coalesce(v_previous_report->'findings', '[]')) f
        union all
        select item, 0 from review_runs r,
          jsonb_array_elements(coalesce(r.diff_json->'unverified_findings', '[]')) item
          where r.id = v_previous
      ) candidates order by item->>'fingerprint', current_rank desc
    ) deduplicated;
    select coalesce(jsonb_agg(f), '[]') into v_new from jsonb_array_elements(v_findings) f
      where not exists (select 1 from jsonb_array_elements(v_previous_findings) old
                        where old->>'fingerprint' = f->>'fingerprint');
    select coalesce(jsonb_agg(f), '[]') into v_existing from jsonb_array_elements(v_findings) f
      where exists (select 1 from jsonb_array_elements(v_previous_findings) old
                    where old->>'fingerprint' = f->>'fingerprint');
    select coalesce(jsonb_agg(old), '[]') into v_resolved
      from jsonb_array_elements(v_previous_findings) old
      where not exists (select 1 from jsonb_array_elements(v_findings) f where f->>'fingerprint' = old->>'fingerprint')
        and review_finding_rechecked(v_report, old);
    select coalesce(jsonb_agg(old), '[]') into v_unverified
      from jsonb_array_elements(v_previous_findings) old
      where not exists (select 1 from jsonb_array_elements(v_findings) f where f->>'fingerprint' = old->>'fingerprint')
        and not review_finding_rechecked(v_report, old);
    select greatest(0, 100 - coalesce(sum(case f->>'severity'
      when 'high' then 25 when 'medium' then 12 when 'low' then 5 when 'info' then 0 else 8 end), 0))
      into v_score from jsonb_array_elements(v_findings) f
      where not exists (select 1 from jsonb_array_elements(v_feedback) fb where fb->>'fingerprint' = f->>'fingerprint'
        and fb->>'status' in ('ignored', 'false_positive')
        and (fb->>'expires_at' is null or (fb->>'expires_at')::timestamptz > now()));
    v_report := jsonb_set(v_report, '{finding_feedback}', v_feedback);
    insert into review_runs(repository_id, status, branch, commit_sha, health_score,
        metrics_json, framework_signals_json, report_json, report_markdown, diff_json,
        new_findings_count, existing_findings_count, resolved_findings_count, created_at)
    values(v_repository, 'completed', p_payload->>'branch', p_payload->>'commit_sha', v_score,
        coalesce(v_report->'metrics', '{}'), coalesce(v_report->'framework_signals', '{}'),
        v_report, p_payload->>'report_markdown', jsonb_build_object(
            'new_findings', v_new, 'existing_findings', v_existing, 'resolved_findings', v_resolved, 'unverified_findings', v_unverified),
        jsonb_array_length(v_new), jsonb_array_length(v_existing), jsonb_array_length(v_resolved), clock_timestamp())
    returning id into v_run;
    insert into findings(review_run_id, fingerprint, title, severity, category, evidence_json,
        evidence_paths_json, recommendation, source, rule_id, path, start_line, end_line, confidence, status)
    select v_run, f->>'fingerprint', f->>'title', f->>'severity', f->>'category',
        coalesce(f->'evidence', '[]'), coalesce(f->'evidence_paths', '[]'), f->>'recommendation',
        coalesce(f->>'source', 'rule'), f->>'rule_id', f->>'path', (f->>'start_line')::integer,
        (f->>'end_line')::integer, (f->>'confidence')::double precision,
        case when exists (select 1 from jsonb_array_elements(v_previous_findings) old
                          where old->>'fingerprint' = f->>'fingerprint') then 'existing' else 'new' end
    from jsonb_array_elements(v_findings) f;
    if v_ai is not null and v_ai <> 'null'::jsonb then
        insert into ai_reviews(review_run_id, provider, model, status, summary, error, sections_json, findings_json)
        values(v_run, v_ai->>'provider', v_ai->>'model', v_ai->>'status', coalesce(v_ai->>'summary', ''),
               v_ai->>'error', coalesce(nullif(v_ai->'sections', 'null'), '{}'), coalesce(v_ai->'findings', '[]'));
    end if;
    v_result := jsonb_build_object('repository_id', v_repository, 'review_run_id', v_run,
        'health_score', v_score, 'finding_feedback', v_feedback,
        'new_findings_count', jsonb_array_length(v_new), 'existing_findings_count', jsonb_array_length(v_existing),
        'resolved_findings_count', jsonb_array_length(v_resolved),
        'unverified_findings_count', jsonb_array_length(v_unverified),
        'comparison', jsonb_build_object('new_findings', v_new, 'existing_findings', v_existing, 'resolved_findings', v_resolved, 'unverified_findings', v_unverified));
    if p_job is not null then
        -- Recheck expiry after any lock waits; the job row lock serializes cancellation.
        if v_job.lease_expires_at <= clock_timestamp() then
            raise exception 'Review job lease expired before commit';
        end if;
        update review_jobs set status = 'completed', phase = 'completed', error = null,
            completed_at = clock_timestamp(), updated_at = clock_timestamp(),
            result_json = jsonb_set(p_result - '_pending_history' - 'markdown', '{report,finding_feedback}', v_feedback)
                          || jsonb_build_object('history', v_result - 'comparison')
        where id = p_job;
    end if;
    insert into review_history_operations(operation_id, owner_id, payload_hash, job_id, result_json)
      values(p_operation, v_owner, v_hash, p_job, v_result);
    return v_result;
end;
$$;
revoke all on function public.save_review_history(jsonb,uuid,uuid,text,jsonb) from public, anon, authenticated;
grant execute on function public.save_review_history(jsonb,uuid,uuid,text,jsonb) to service_role;
commit;
