-- Apply after the existing review_jobs migration. Only the backend service role
-- may enqueue/claim/recover; browser clients retain owner-scoped read access.
alter table public.review_jobs add column if not exists phase text not null default 'queued';
alter table public.review_jobs add column if not exists lease_token text;
alter table public.review_jobs add column if not exists lease_expires_at timestamptz;
alter table public.review_jobs add column if not exists attempts integer not null default 0;
create index if not exists review_jobs_queue on public.review_jobs(status, created_at);

create or replace function public.enqueue_review_job(p_target text, p_request jsonb, p_owner uuid,
    p_max_pending integer, p_per_user integer) returns setof public.review_jobs
language plpgsql security definer set search_path = public as $$
begin
    -- Serialize admission across instances, including the shared anonymous bucket.
    perform pg_advisory_xact_lock(735019421);
    if (select count(*) from review_jobs where status in ('queued','running')) >= p_max_pending
       or (select count(*) from review_jobs where status in ('queued','running')
           and owner_id is not distinct from p_owner) >= p_per_user then
        return;
    end if;
    return query insert into review_jobs(target, request_json, owner_id, status, phase)
        values(p_target, p_request, p_owner, 'queued', 'queued') returning *;
end;
$$;

create or replace function public.claim_review_job(p_token text, p_lease_seconds integer)
returns setof public.review_jobs language plpgsql security definer set search_path = public as $$
begin
    return query update review_jobs set status = 'running', phase = 'cloning',
        lease_token = p_token, lease_expires_at = now() + make_interval(secs => p_lease_seconds),
        started_at = now(), updated_at = now(), attempts = attempts + 1
    where id = (select id from review_jobs where status = 'queued'
                order by created_at for update skip locked limit 1)
    returning *;
end;
$$;

create or replace function public.recover_review_jobs(p_result_ttl integer)
returns void language plpgsql security definer set search_path = public as $$
begin
    update review_jobs set status = case when attempts >= 3 then 'failed' else 'queued' end,
        phase = case when attempts >= 3 then 'failed' else 'queued' end,
        error = case when attempts >= 3 then 'Review could not finish after three worker attempts.' else null end,
        completed_at = case when attempts >= 3 then now() else null end,
        lease_token = null, lease_expires_at = null, updated_at = now()
    where status = 'running' and (lease_expires_at is null or lease_expires_at < now());
    delete from review_jobs where status in ('completed','failed')
        and coalesce(completed_at, updated_at) < now() - make_interval(secs => p_result_ttl);
end;
$$;
revoke all on function public.enqueue_review_job(text,jsonb,uuid,integer,integer) from public, anon, authenticated;
revoke all on function public.claim_review_job(text,integer) from public, anon, authenticated;
revoke all on function public.recover_review_jobs(integer) from public, anon, authenticated;
grant execute on function public.enqueue_review_job(text,jsonb,uuid,integer,integer) to service_role;
grant execute on function public.claim_review_job(text,integer) to service_role;
grant execute on function public.recover_review_jobs(integer) to service_role;
