-- Shared AI-question admission across API processes; service role only.
create table if not exists public.review_question_leases (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    admitted_at timestamptz not null default clock_timestamp(),
    expires_at timestamptz not null,
    released boolean not null default false
);
create index if not exists review_question_leases_owner_time
    on public.review_question_leases(owner_id, admitted_at);
alter table public.review_question_leases enable row level security;
revoke all on public.review_question_leases from public, anon, authenticated;
grant all on public.review_question_leases to service_role;

create or replace function public.acquire_review_question(
    p_owner uuid, p_global_limit integer, p_user_limit integer,
    p_rate_limit integer, p_lease_seconds integer
) returns uuid language plpgsql security definer set search_path=public as $$
declare
    lease_now timestamptz;
    lease uuid;
begin
    if p_owner is null or p_global_limit is null or p_global_limit < 1
      or p_user_limit is null or p_user_limit < 1
      or p_rate_limit is null or p_rate_limit < 1
      or p_lease_seconds is null or p_lease_seconds < 1 then
        raise exception 'Invalid question admission limits';
    end if;
    perform pg_advisory_xact_lock(735019422);
    lease_now := clock_timestamp();
    delete from review_question_leases
      where admitted_at <= lease_now - interval '1 minute'
        and (released or expires_at <= lease_now);
    if (select count(*) from review_question_leases
        where not released and expires_at > lease_now) >= p_global_limit
      or (select count(*) from review_question_leases
          where owner_id=p_owner and not released and expires_at > lease_now) >= p_user_limit
      or (select count(*) from review_question_leases
          where owner_id=p_owner and admitted_at > lease_now - interval '1 minute') >= p_rate_limit then
        return null;
    end if;
    insert into review_question_leases(owner_id, admitted_at, expires_at)
      values (p_owner, lease_now, lease_now + make_interval(secs => p_lease_seconds))
      returning id into lease;
    return lease;
end;
$$;
create or replace function public.release_review_question(p_lease uuid)
returns void language sql security definer set search_path=public as $$
    update review_question_leases set released=true where id=p_lease;
$$;
revoke all on function public.acquire_review_question(uuid,integer,integer,integer,integer) from public,anon,authenticated;
revoke all on function public.release_review_question(uuid) from public,anon,authenticated;
grant execute on function public.acquire_review_question(uuid,integer,integer,integer,integer) to service_role;
grant execute on function public.release_review_question(uuid) to service_role;
