-- GitHub Repo Review Agent history schema.
-- Run this in the Supabase SQL Editor before using `repo-review --save-history`.
-- The CLI/server should use SUPABASE_SERVICE_ROLE_KEY. Never expose that key in browser code.

create extension if not exists pgcrypto;

create table if not exists public.repositories (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,
  repo_url text not null,
  repo_name text not null,
  default_branch text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Earlier versions used a global unique constraint on repo_url. That works for a
-- single-user portfolio demo, but a SaaS/demo with login needs each user to own
-- an independent history for the same repository URL.
alter table public.repositories drop constraint if exists repositories_repo_url_key;

-- User-owned repository history should be deleted with the account. Using
-- cascade also prevents deleted users from turning duplicate repo URLs into
-- anonymous rows that collide with the anonymous unique index below.
alter table public.repositories drop constraint if exists repositories_owner_id_fkey;
alter table public.repositories
  add constraint repositories_owner_id_fkey
  foreign key (owner_id) references auth.users(id) on delete cascade;

create table if not exists public.review_runs (
  id uuid primary key default gen_random_uuid(),
  repository_id uuid not null references public.repositories(id) on delete cascade,
  status text not null default 'completed' check (status in ('completed', 'failed')),
  commit_sha text,
  branch text,
  health_score integer check (health_score between 0 and 100),
  metrics_json jsonb not null default '{}'::jsonb,
  framework_signals_json jsonb not null default '{}'::jsonb,
  report_json jsonb not null,
  report_markdown text not null,
  diff_json jsonb not null default '{}'::jsonb,
  new_findings_count integer not null default 0,
  existing_findings_count integer not null default 0,
  resolved_findings_count integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists public.findings (
  id uuid primary key default gen_random_uuid(),
  review_run_id uuid not null references public.review_runs(id) on delete cascade,
  fingerprint text not null,
  title text not null,
  severity text not null check (severity in ('info', 'low', 'medium', 'high')),
  category text not null,
  evidence_json jsonb not null default '[]'::jsonb,
  evidence_paths_json jsonb not null default '[]'::jsonb,
  recommendation text not null,
  status text not null default 'new' check (status in ('new', 'existing')),
  created_at timestamptz not null default now(),
  unique (review_run_id, fingerprint)
);

create table if not exists public.ai_reviews (
  id uuid primary key default gen_random_uuid(),
  review_run_id uuid not null references public.review_runs(id) on delete cascade,
  provider text not null,
  model text not null,
  status text not null,
  summary text not null default '',
  error text,
  sections_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists review_runs_repository_created_idx
  on public.review_runs (repository_id, created_at desc);

create index if not exists repositories_owner_updated_idx
  on public.repositories (owner_id, updated_at desc);

create unique index if not exists repositories_owner_repo_url_unique_idx
  on public.repositories (owner_id, repo_url)
  where owner_id is not null;

create unique index if not exists repositories_anonymous_repo_url_unique_idx
  on public.repositories (repo_url)
  where owner_id is null;

create index if not exists findings_review_run_status_idx
  on public.findings (review_run_id, status);

create index if not exists findings_fingerprint_idx
  on public.findings (fingerprint);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists repositories_set_updated_at on public.repositories;
create trigger repositories_set_updated_at
before update on public.repositories
for each row execute function public.set_updated_at();

alter table public.repositories enable row level security;
alter table public.review_runs enable row level security;
alter table public.findings enable row level security;
alter table public.ai_reviews enable row level security;

drop policy if exists repositories_select_own on public.repositories;
create policy repositories_select_own
on public.repositories
for select
using (owner_id = auth.uid());

drop policy if exists review_runs_select_own on public.review_runs;
create policy review_runs_select_own
on public.review_runs
for select
using (
  exists (
    select 1
    from public.repositories
    where repositories.id = review_runs.repository_id
      and repositories.owner_id = auth.uid()
  )
);

drop policy if exists findings_select_own on public.findings;
create policy findings_select_own
on public.findings
for select
using (
  exists (
    select 1
    from public.review_runs
    join public.repositories on repositories.id = review_runs.repository_id
    where review_runs.id = findings.review_run_id
      and repositories.owner_id = auth.uid()
  )
);

drop policy if exists ai_reviews_select_own on public.ai_reviews;
create policy ai_reviews_select_own
on public.ai_reviews
for select
using (
  exists (
    select 1
    from public.review_runs
    join public.repositories on repositories.id = review_runs.repository_id
    where review_runs.id = ai_reviews.review_run_id
      and repositories.owner_id = auth.uid()
  )
);
