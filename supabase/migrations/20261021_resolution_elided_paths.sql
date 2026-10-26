-- Apply after 20261008_resolution_coverage.sql.
-- A compressed API report removes inventory_paths but keeps inventory_complete.
-- Missing evidence must not be mistaken for an empty inventory (deleted files).
begin;

create or replace function public.review_finding_rechecked(p_report jsonb, p_finding jsonb)
returns boolean language plpgsql immutable set search_path = public, pg_temp as $$
declare
  coverage jsonb := p_report #> '{metrics,review_coverage}';
  paths jsonb := coalesce(p_finding->'evidence_paths', '[]');
begin
  if review_policy(p_report) is distinct from p_finding #> '{resolution_context,policy}'
     or coverage->>'version' is distinct from '1' then return false; end if;
  if nullif(p_finding->>'path', '') is not null then
    paths := paths || jsonb_build_array(p_finding->>'path');
  end if;
  if jsonb_array_length(paths)>0
     and p_finding #>> '{resolution_context,evidence_was_present}' = 'true'
     and coverage->>'inventory_complete' = 'true'
     and coalesce(coverage->>'inventory_paths_elided', 'false') <> 'true'
     and coverage ? 'inventory_paths'
     and not exists (select 1 from jsonb_array_elements_text(paths) path
                     where (coverage->'inventory_paths') ? path)
  then return true; end if;
  if p_finding->>'source' = 'ai' then return false; end if;
  if p_finding->>'rule_id' = 'dependency.osv' or p_finding->>'category' = 'dependency vulnerabilities'
  then return coalesce(coverage->>'inventory_complete' = 'true', false)
              and coalesce(p_report #>> '{metrics,vulnerability_scan,status}' in ('clean','findings'), false); end if;
  if p_finding->>'title' like 'Fix % Ruff %'
  then return coalesce(coverage->>'ruff_complete' = 'true', false); end if;
  return coalesce(coverage->>'rules_complete' = 'true', false);
end;
$$;
revoke all on function public.review_finding_rechecked(jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.review_finding_rechecked(jsonb,jsonb) to service_role;

commit;
