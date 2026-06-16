-- Harden repository ownership for multi-user SaaS/demo deployments.
-- Run this after older schema versions that used a global repo_url uniqueness
-- constraint or set repository owner_id to null when an auth user was deleted.

alter table public.repositories drop constraint if exists repositories_repo_url_key;

alter table public.repositories drop constraint if exists repositories_owner_id_fkey;
alter table public.repositories
  add constraint repositories_owner_id_fkey
  foreign key (owner_id) references auth.users(id) on delete cascade;

create index if not exists repositories_owner_updated_idx
  on public.repositories (owner_id, updated_at desc);

create unique index if not exists repositories_owner_repo_url_unique_idx
  on public.repositories (owner_id, repo_url)
  where owner_id is not null;

create unique index if not exists repositories_anonymous_repo_url_unique_idx
  on public.repositories (repo_url)
  where owner_id is null;
