-- Supabase history schema verification.
-- Run this in the Supabase SQL Editor after supabase/schema.sql or the latest
-- migration. Every row should return status = 'pass' before an end-to-end demo.

with checks as (
  select
    'table: repositories' as check_name,
    to_regclass('public.repositories') is not null as ok,
    'repository ownership and project list root table' as detail
  union all
  select
    'table: review_runs',
    to_regclass('public.review_runs') is not null,
    'saved review report runs'
  union all
  select
    'table: review_jobs',
    to_regclass('public.review_jobs') is not null,
    'persistent async web review jobs'
  union all
  select
    'table: findings',
    to_regclass('public.findings') is not null,
    'per-run finding snapshots'
  union all
  select
    'table: ai_reviews',
    to_regclass('public.ai_reviews') is not null,
    'optional AI review sections'
  union all
  select
    'foreign key: repositories_owner_id_fkey cascade',
    exists (
      select 1
      from pg_constraint
      where conname = 'repositories_owner_id_fkey'
        and contype = 'f'
        and confdeltype = 'c'
    ),
    'repository rows are removed when the owning auth user is deleted'
  union all
  select
    'index: repositories_owner_updated_idx',
    exists (
      select 1
      from pg_indexes
      where schemaname = 'public'
        and tablename = 'repositories'
        and indexname = 'repositories_owner_updated_idx'
    ),
    'fast project list queries by owner and updated_at'
  union all
  select
    'index: repositories_owner_repo_url_unique_idx',
    exists (
      select 1
      from pg_indexes
      where schemaname = 'public'
        and tablename = 'repositories'
        and indexname = 'repositories_owner_repo_url_unique_idx'
        and indexdef ilike '%unique%'
        and indexdef ilike '%owner_id%'
        and indexdef ilike '%repo_url%'
    ),
    'signed-in users can each own one history row per repo URL'
  union all
  select
    'index: repositories_anonymous_repo_url_unique_idx',
    exists (
      select 1
      from pg_indexes
      where schemaname = 'public'
        and tablename = 'repositories'
        and indexname = 'repositories_anonymous_repo_url_unique_idx'
        and indexdef ilike '%unique%'
        and indexdef ilike '%repo_url%'
    ),
    'anonymous CLI/server history rows stay unique by repo URL'
  union all
  select
    'index: review_jobs_owner_created_idx',
    exists (
      select 1
      from pg_indexes
      where schemaname = 'public'
        and tablename = 'review_jobs'
        and indexname = 'review_jobs_owner_created_idx'
    ),
    'fast review job lookup by owner and created_at'
  union all
  select
    'index: review_jobs_status_updated_idx',
    exists (
      select 1
      from pg_indexes
      where schemaname = 'public'
        and tablename = 'review_jobs'
        and indexname = 'review_jobs_status_updated_idx'
    ),
    'fast stale running job cleanup'
  union all
  select
    'rls: repositories',
    exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = 'repositories'
        and c.relrowsecurity
    ),
    'row level security enabled for repositories'
  union all
  select
    'rls: review_runs',
    exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = 'review_runs'
        and c.relrowsecurity
    ),
    'row level security enabled for review runs'
  union all
  select
    'rls: review_jobs',
    exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = 'review_jobs'
        and c.relrowsecurity
    ),
    'row level security enabled for async review jobs'
  union all
  select
    'rls: findings',
    exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = 'findings'
        and c.relrowsecurity
    ),
    'row level security enabled for findings'
  union all
  select
    'rls: ai_reviews',
    exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = 'ai_reviews'
        and c.relrowsecurity
    ),
    'row level security enabled for AI reviews'
  union all
  select
    'policy: repositories_select_own',
    exists (
      select 1
      from pg_policies
      where schemaname = 'public'
        and tablename = 'repositories'
        and policyname = 'repositories_select_own'
    ),
    'authenticated users can only select their own repositories'
  union all
  select
    'policy: review_runs_select_own',
    exists (
      select 1
      from pg_policies
      where schemaname = 'public'
        and tablename = 'review_runs'
        and policyname = 'review_runs_select_own'
    ),
    'review runs are readable through owned repositories'
  union all
  select
    'policy: review_jobs_select_own',
    exists (
      select 1
      from pg_policies
      where schemaname = 'public'
        and tablename = 'review_jobs'
        and policyname = 'review_jobs_select_own'
    ),
    'authenticated users can only select their own async review jobs'
  union all
  select
    'privilege: service_role review_jobs read/write',
    has_schema_privilege('service_role', 'public', 'USAGE')
      and has_table_privilege('service_role', 'public.review_jobs', 'SELECT')
      and has_table_privilege('service_role', 'public.review_jobs', 'INSERT')
      and has_table_privilege('service_role', 'public.review_jobs', 'UPDATE')
      and has_table_privilege('service_role', 'public.review_jobs', 'DELETE'),
    'backend service role can create, update, read, and clean up persistent review jobs'
  union all
  select
    'privilege: authenticated review_jobs select',
    has_table_privilege('authenticated', 'public.review_jobs', 'SELECT'),
    'authenticated users can read review jobs through RLS'
  union all
  select
    'policy: findings_select_own',
    exists (
      select 1
      from pg_policies
      where schemaname = 'public'
        and tablename = 'findings'
        and policyname = 'findings_select_own'
    ),
    'findings are readable through owned repositories'
  union all
  select
    'policy: ai_reviews_select_own',
    exists (
      select 1
      from pg_policies
      where schemaname = 'public'
        and tablename = 'ai_reviews'
        and policyname = 'ai_reviews_select_own'
    ),
    'AI reviews are readable through owned repositories'
)
select
  check_name,
  case when ok then 'pass' else 'fail' end as status,
  detail
from checks
order by check_name;

-- If a unique index check failed during migration, look for duplicates with:
--
-- select owner_id, repo_url, count(*)
-- from public.repositories
-- where owner_id is not null
-- group by owner_id, repo_url
-- having count(*) > 1;
--
-- select repo_url, count(*)
-- from public.repositories
-- where owner_id is null
-- group by repo_url
-- having count(*) > 1;
