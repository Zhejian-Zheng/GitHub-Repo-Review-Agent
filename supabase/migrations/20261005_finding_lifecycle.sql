-- Apply after 001-004 and 20261004_review_job_leases.sql, before deploying lifecycle code.
begin;

alter table public.findings
  add column if not exists source text not null default 'rule' check (source in ('rule', 'ai')),
  add column if not exists rule_id text,
  add column if not exists path text,
  add column if not exists start_line integer check (start_line > 0),
  add column if not exists end_line integer check (end_line >= start_line),
  add column if not exists confidence double precision check (confidence between 0 and 1);
alter table public.ai_reviews add column if not exists findings_json jsonb not null default '[]'::jsonb;

create table if not exists public.finding_feedback (
  repository_id uuid not null references public.repositories(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  fingerprint text not null,
  status text not null check (status in ('confirmed', 'false_positive', 'ignored')),
  reason text not null default '' check (char_length(reason) <= 4000),
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (repository_id, owner_id, fingerprint)
);

alter table public.finding_feedback enable row level security;
drop policy if exists finding_feedback_select_own on public.finding_feedback;
create policy finding_feedback_select_own on public.finding_feedback for select
using (owner_id = auth.uid() and exists (
  select 1 from public.repositories r
  where r.id = finding_feedback.repository_id and r.owner_id = auth.uid()
));
-- Mutations go through the server's ownership/finding checks using service_role.
revoke all on public.finding_feedback from anon, authenticated;
grant select on public.finding_feedback to authenticated;
grant all on public.finding_feedback to service_role;

drop trigger if exists finding_feedback_set_updated_at on public.finding_feedback;
create trigger finding_feedback_set_updated_at before update on public.finding_feedback
for each row execute function public.set_updated_at();

commit;
