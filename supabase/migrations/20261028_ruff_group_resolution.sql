-- Apply after 20261023_inventory_rule_coverage.sql. No stored identities are rewritten.
begin;

create or replace function public.review_ruff_rule_code(p_finding jsonb)
returns text language sql immutable set search_path = public, pg_temp as $$
  select case when coalesce(p_finding->>'source', 'rule') = 'rule' then coalesce(
    substring(p_finding->>'rule_id' from '^ruff\.([A-Z][A-Z0-9]*|syntax-error)$'),
    substring(p_finding->>'title' from '^Fix [0-9]+ Ruff ([A-Z][A-Z0-9]*|syntax-error) lint finding\(s\)$')
  ) end;
$$;
revoke all on function public.review_ruff_rule_code(jsonb) from public, anon, authenticated;
grant execute on function public.review_ruff_rule_code(jsonb) to service_role;

create or replace function public.review_finding_rechecked(p_report jsonb, p_finding jsonb)
returns boolean language plpgsql immutable set search_path = public, pg_temp as $$
declare
  coverage jsonb := p_report #> '{metrics,review_coverage}';
  paths jsonb := coalesce(p_finding->'evidence_paths', '[]');
  ruff_code text := review_ruff_rule_code(p_finding);
begin
  if review_policy(p_report) is distinct from p_finding #> '{resolution_context,policy}'
     or coverage->>'version' is distinct from '1' then return false; end if;
  if ruff_code is not null then
    -- Counts, sampled paths and legacy fingerprints can change while the group persists.
    return coalesce(coverage->>'ruff_complete' = 'true', false)
       and not exists (
         select 1 from jsonb_array_elements(coalesce(p_report->'findings', '[]')
                     || coalesce(p_report->'raw_findings', '[]')) item
         where review_ruff_rule_code(item) = ruff_code
       );
  end if;
  if nullif(p_finding->>'path', '') is not null then
    paths := paths || jsonb_build_array(p_finding->>'path');
  end if;
  if jsonb_array_length(paths)>0
     and p_finding #>> '{resolution_context,evidence_was_present}' = 'true'
     and coverage->>'inventory_complete' = 'true'
     and coalesce(coverage->>'inventory_paths_elided', 'false') <> 'true'
     and coverage ? 'inventory_paths'
     and not exists (select 1 from jsonb_array_elements_text(paths) path
                     where (coverage->'inventory_paths') ? path)
  then return true; end if;
  if p_finding->>'source' = 'ai' then return false; end if;
  if p_finding->>'rule_id' = 'dependency.osv' or p_finding->>'category' = 'dependency vulnerabilities'
  then return coalesce(coverage->>'inventory_complete' = 'true', false)
              and coalesce(p_report #>> '{metrics,vulnerability_scan,status}' in ('clean','findings'), false); end if;
  if jsonb_typeof(coverage->'completed_rules') = 'array'
     and (coverage->'completed_rules') ? (p_finding->>'title')
  then return true; end if;
  return coalesce(coverage->>'rules_complete' = 'true', false);
end;
$$;
revoke all on function public.review_finding_rechecked(jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.review_finding_rechecked(jsonb,jsonb) to service_role;

commit;
