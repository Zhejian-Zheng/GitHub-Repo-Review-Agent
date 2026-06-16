-- Grant API roles access to the history and async job tables.
-- Run this after 001_initial_schema.sql, 002_repository_ownership_hardening.sql,
-- and 003_review_jobs.sql on existing Supabase projects.

grant usage on schema public to service_role, authenticated;

grant select, insert, update, delete on public.repositories to service_role;
grant select, insert, update, delete on public.review_runs to service_role;
grant select, insert, update, delete on public.findings to service_role;
grant select, insert, update, delete on public.ai_reviews to service_role;
grant select, insert, update, delete on public.review_jobs to service_role;

grant select on public.repositories to authenticated;
grant select on public.review_runs to authenticated;
grant select on public.findings to authenticated;
grant select on public.ai_reviews to authenticated;
grant select on public.review_jobs to authenticated;
