-- Atomic UTC-day admission, and owner-scoped cancellation fenced against workers.
alter table public.review_jobs drop constraint if exists review_jobs_status_check;
alter table public.review_jobs add constraint review_jobs_status_check
  check (status in ('queued','running','completed','failed','cancelled'));
create table if not exists public.review_daily_usage (
  quota_day date not null,
  owner_key text not null,
  admissions integer not null default 0,
  primary key (quota_day, owner_key)
);
alter table public.review_daily_usage enable row level security;
grant select,insert,update,delete on public.review_daily_usage to service_role;

drop function if exists public.enqueue_review_job(text,jsonb,uuid,integer,integer);
create or replace function public.enqueue_review_job(p_target text, p_request jsonb, p_owner uuid,
  p_max_pending integer, p_per_user integer, p_daily_limit integer default 100)
returns setof public.review_jobs language plpgsql security definer set search_path = public as $$
declare
  day_utc date := (now() at time zone 'UTC')::date;
  owner_bucket text := coalesce(p_owner::text, 'anonymous');
begin
  perform pg_advisory_xact_lock(735019421);
  if p_daily_limit < 1 or p_max_pending < 1 or p_per_user < 1 then
    raise exception 'Invalid review admission limits';
  end if;
  if (select count(*) from review_jobs where status in ('queued','running')) >= p_max_pending
    or (select count(*) from review_jobs where status in ('queued','running')
      and owner_id is not distinct from p_owner) >= p_per_user then return; end if;
  insert into review_daily_usage(quota_day,owner_key) values(day_utc,owner_bucket)
    on conflict do nothing;
  if (select admissions from review_daily_usage where quota_day=day_utc and owner_key=owner_bucket)
    >= p_daily_limit then return; end if;
  update review_daily_usage set admissions=admissions+1 where quota_day=day_utc and owner_key=owner_bucket;
  delete from review_daily_usage where quota_day < day_utc - 7;
  return query insert into review_jobs(target,request_json,owner_id,status,phase)
    values(p_target,p_request,p_owner,'queued','queued') returning *;
end;
$$;

create or replace function public.cancel_review_job(p_job uuid,p_owner uuid)
returns setof public.review_jobs language plpgsql security definer set search_path = public as $$
begin
  -- Clearing the lease rejects completion writes even during a cancellation race.
  update review_jobs set status='cancelled',phase='cancelled',result_json=null,error=null,
    lease_token=null,lease_expires_at=null,completed_at=now(),updated_at=now()
    where id=p_job and owner_id=p_owner and p_owner is not null and status in ('queued','running');
  return query select * from review_jobs where id=p_job and owner_id=p_owner and p_owner is not null;
end;
$$;

create or replace function public.recover_review_jobs(p_result_ttl integer)
returns void language plpgsql security definer set search_path = public as $$
begin
  update review_jobs set status=case when attempts>=3 then 'failed' else 'queued' end,
    phase=case when attempts>=3 then 'failed' else 'queued' end,
    error=case when attempts>=3 then 'Review could not finish after three worker attempts.' else null end,
    completed_at=case when attempts>=3 then now() else null end,
    lease_token=null,lease_expires_at=null,updated_at=now()
    where status='running' and (lease_expires_at is null or lease_expires_at<now());
  delete from review_jobs where status in ('completed','failed','cancelled')
    and coalesce(completed_at,updated_at)<now()-make_interval(secs=>p_result_ttl);
end;
$$;
revoke all on function public.enqueue_review_job(text,jsonb,uuid,integer,integer,integer) from public,anon,authenticated;
revoke all on function public.cancel_review_job(uuid,uuid) from public,anon,authenticated;
grant execute on function public.enqueue_review_job(text,jsonb,uuid,integer,integer,integer) to service_role;
grant execute on function public.cancel_review_job(uuid,uuid) to service_role;

create or replace function public.admit_review_question(p_owner uuid,p_daily_limit integer)
returns boolean language plpgsql security definer set search_path = public as $$
declare day_utc date := (now() at time zone 'UTC')::date;
begin
  if p_owner is null or p_daily_limit<1 then return false; end if;
  perform pg_advisory_xact_lock(735019421);
  insert into review_daily_usage(quota_day,owner_key) values(day_utc,p_owner::text) on conflict do nothing;
  if (select admissions from review_daily_usage where quota_day=day_utc and owner_key=p_owner::text)
    >=p_daily_limit then return false; end if;
  update review_daily_usage set admissions=admissions+1 where quota_day=day_utc and owner_key=p_owner::text;
  return true;
end;
$$;
revoke all on function public.admit_review_question(uuid,integer) from public,anon,authenticated;
grant execute on function public.admit_review_question(uuid,integer) to service_role;
