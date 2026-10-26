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
    'privilege: service_role history tables read/write',
    has_schema_privilege('service_role', 'public', 'USAGE')
      and has_table_privilege('service_role', 'public.repositories', 'SELECT')
      and has_table_privilege('service_role', 'public.repositories', 'INSERT')
      and has_table_privilege('service_role', 'public.repositories', 'UPDATE')
      and has_table_privilege('service_role', 'public.repositories', 'DELETE')
      and has_table_privilege('service_role', 'public.review_runs', 'SELECT')
      and has_table_privilege('service_role', 'public.review_runs', 'INSERT')
      and has_table_privilege('service_role', 'public.review_runs', 'UPDATE')
      and has_table_privilege('service_role', 'public.review_runs', 'DELETE')
      and has_table_privilege('service_role', 'public.findings', 'SELECT')
      and has_table_privilege('service_role', 'public.findings', 'INSERT')
      and has_table_privilege('service_role', 'public.findings', 'UPDATE')
      and has_table_privilege('service_role', 'public.findings', 'DELETE')
      and has_table_privilege('service_role', 'public.ai_reviews', 'SELECT')
      and has_table_privilege('service_role', 'public.ai_reviews', 'INSERT')
      and has_table_privilege('service_role', 'public.ai_reviews', 'UPDATE')
      and has_table_privilege('service_role', 'public.ai_reviews', 'DELETE')
      and has_table_privilege('service_role', 'public.review_jobs', 'SELECT')
      and has_table_privilege('service_role', 'public.review_jobs', 'INSERT')
      and has_table_privilege('service_role', 'public.review_jobs', 'UPDATE')
      and has_table_privilege('service_role', 'public.review_jobs', 'DELETE'),
    'backend service role can create, update, read, and clean up saved reviews and persistent jobs'
  union all
  select
    'privilege: authenticated history tables select',
    has_schema_privilege('authenticated', 'public', 'USAGE')
      and has_table_privilege('authenticated', 'public.repositories', 'SELECT')
      and has_table_privilege('authenticated', 'public.review_runs', 'SELECT')
      and has_table_privilege('authenticated', 'public.findings', 'SELECT')
      and has_table_privilege('authenticated', 'public.ai_reviews', 'SELECT')
      and has_table_privilege('authenticated', 'public.review_jobs', 'SELECT'),
    'authenticated users can read owned saved reviews and review jobs through RLS'
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
  union all
  select
    'columns: review job leases',
    exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'review_jobs' and column_name = 'phase'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'review_jobs' and column_name = 'lease_token'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'review_jobs' and column_name = 'lease_expires_at'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'review_jobs' and column_name = 'attempts'
    ),
    'review jobs support atomic claims, leases, phases and bounded retries'
  union all
  select
    'constraint: review job status includes cancelled',
    exists (
      select 1 from pg_constraint
      where conname = 'review_jobs_status_check'
        and contype = 'c'
        and pg_get_constraintdef(oid) ilike '%cancelled%'
    ),
    'owner cancellation has a durable terminal status'
  union all
  select
    'columns: finding lifecycle and AI evidence',
    exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'findings' and column_name = 'source'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'findings' and column_name = 'rule_id'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'findings' and column_name = 'path'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'findings' and column_name = 'start_line'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'findings' and column_name = 'end_line'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'findings' and column_name = 'confidence'
    ) and exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'ai_reviews' and column_name = 'findings_json'
    ),
    'findings retain source, location and AI evidence fields'
  union all
  select
    'table: finding_feedback',
    to_regclass('public.finding_feedback') is not null,
    'owner-scoped finding decisions are durable'
  union all
  select
    'table: review_daily_usage',
    to_regclass('public.review_daily_usage') is not null,
    'daily review and question admissions are shared'
  union all
  select
    'table: review_question_leases',
    to_regclass('public.review_question_leases') is not null,
    'AI question capacity is shared across API processes'
  union all
  select
    'table: review_history_operations',
    to_regclass('public.review_history_operations') is not null,
    'history writes are idempotent across retries'
  union all
  select
    'function: review job RPCs',
    to_regprocedure('public.enqueue_review_job(text,jsonb,uuid,integer,integer,integer)') is not null
      and to_regprocedure('public.claim_review_job(text,integer)') is not null
      and to_regprocedure('public.recover_review_jobs(integer)') is not null
      and to_regprocedure('public.cancel_review_job(uuid,uuid)') is not null
      and to_regprocedure('public.admit_review_question(uuid,integer)') is not null,
    'queue admission, leasing, recovery, cancellation and daily quotas are installed'
  union all
  select
    'function: history and resolution RPCs',
    to_regprocedure('public.save_review_history(jsonb,uuid,uuid,text,jsonb)') is not null
      and to_regprocedure('public.review_policy(jsonb)') is not null
      and to_regprocedure('public.review_finding_rechecked(jsonb,jsonb)') is not null,
    'atomic history and coverage-aware resolution are installed'
  union all
  select
    'function: compressed reports cannot prove deletion',
    exists (
      select 1 from pg_proc p
      where p.oid = to_regprocedure('public.review_finding_rechecked(jsonb,jsonb)')::oid
        and p.prosrc ilike '%inventory_paths_elided%'
    ),
    'resolution rejects inventory paths removed for display or model prompts'
  union all
  select
    'function: inventory rule coverage',
    exists (
      select 1 from pg_proc p
      where p.oid = to_regprocedure('public.review_finding_rechecked(jsonb,jsonb)')::oid
        and p.prosrc ilike '%completed_rules%'
    ),
    'completed inventory checks can resolve independently of content scan limits'
  union all
  select
    'function: question capacity RPCs',
    to_regprocedure('public.acquire_review_question(uuid,integer,integer,integer,integer)') is not null
      and to_regprocedure('public.release_review_question(uuid)') is not null,
    'shared question admission and release RPCs are installed'
  union all
  select
    'rls: lifecycle and leasing tables',
    exists (
      select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = 'finding_feedback' and c.relrowsecurity
    ) and exists (
      select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = 'review_daily_usage' and c.relrowsecurity
    ) and exists (
      select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = 'review_question_leases' and c.relrowsecurity
    ) and exists (
      select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = 'review_history_operations' and c.relrowsecurity
    ),
    'new ownership, quota and lease tables keep RLS enabled'
  union all
  select
    'privilege: service_role lifecycle and leasing tables',
    exists (
      select 1 from information_schema.role_table_grants
      where table_schema = 'public' and table_name = 'finding_feedback'
        and grantee = 'service_role' and privilege_type = 'SELECT'
    ) and exists (
      select 1 from information_schema.role_table_grants
      where table_schema = 'public' and table_name = 'review_daily_usage'
        and grantee = 'service_role' and privilege_type = 'INSERT'
    ) and exists (
      select 1 from information_schema.role_table_grants
      where table_schema = 'public' and table_name = 'review_question_leases'
        and grantee = 'service_role' and privilege_type = 'SELECT'
    ) and exists (
      select 1 from information_schema.role_table_grants
      where table_schema = 'public' and table_name = 'review_history_operations'
        and grantee = 'service_role' and privilege_type = 'INSERT'
    ),
    'backend service role can operate the new lifecycle and leasing tables'
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
