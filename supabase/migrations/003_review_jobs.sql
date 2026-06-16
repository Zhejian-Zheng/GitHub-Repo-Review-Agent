-- Persist asynchronous web review jobs for hosted demos.
-- Run this after 001_initial_schema.sql and 002_repository_ownership_hardening.sql.

create table if not exists public.review_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) on delete cascade,
  status text not null default 'queued' check (status in ('queued', 'running', 'completed', 'failed')),
  target text not null,
  request_json jsonb not null default '{}'::jsonb,
  result_json jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

create index if not exists review_jobs_owner_created_idx
  on public.review_jobs (owner_id, created_at desc);

create index if not exists review_jobs_status_updated_idx
  on public.review_jobs (status, updated_at);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists review_jobs_set_updated_at on public.review_jobs;
create trigger review_jobs_set_updated_at
before update on public.review_jobs
for each row execute function public.set_updated_at();

alter table public.review_jobs enable row level security;

drop policy if exists review_jobs_select_own on public.review_jobs;
create policy review_jobs_select_own
on public.review_jobs
for select
using (owner_id = auth.uid());
