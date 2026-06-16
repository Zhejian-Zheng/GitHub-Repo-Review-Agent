import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "supabase" / "schema.sql"
MIGRATIONS = ROOT / "supabase" / "migrations"
VERIFY_SCHEMA = ROOT / "supabase" / "verify_history_schema.sql"


class SupabaseSchemaTests(unittest.TestCase):
    def test_schema_uses_cascade_owner_cleanup(self) -> None:
        schema = SCHEMA.read_text(encoding="utf-8").lower()

        self.assertIn("drop constraint if exists repositories_owner_id_fkey", schema)
        self.assertIn("references auth.users(id) on delete cascade", schema)
        self.assertNotIn("on delete set null", schema)

    def test_schema_indexes_owner_history_queries(self) -> None:
        schema = SCHEMA.read_text(encoding="utf-8").lower()

        self.assertIn("repositories_owner_updated_idx", schema)
        self.assertIn("on public.repositories (owner_id, updated_at desc)", schema)
        self.assertIn("repositories_owner_repo_url_unique_idx", schema)
        self.assertIn("repositories_anonymous_repo_url_unique_idx", schema)

    def test_schema_migrations_are_present(self) -> None:
        migrations = {path.name for path in MIGRATIONS.glob("*.sql")}

        self.assertIn("001_initial_schema.sql", migrations)
        self.assertIn("002_repository_ownership_hardening.sql", migrations)
        self.assertIn("003_review_jobs.sql", migrations)

    def test_schema_persists_async_review_jobs(self) -> None:
        schema = SCHEMA.read_text(encoding="utf-8").lower()

        self.assertIn("create table if not exists public.review_jobs", schema)
        self.assertIn("status in ('queued', 'running', 'completed', 'failed')", schema)
        self.assertIn("request_json jsonb not null", schema)
        self.assertIn("result_json jsonb", schema)
        self.assertIn("review_jobs_owner_created_idx", schema)
        self.assertIn("review_jobs_status_updated_idx", schema)
        self.assertIn("alter table public.review_jobs enable row level security", schema)
        self.assertIn("review_jobs_select_own", schema)
        self.assertIn("grant select, insert, update, delete on public.review_jobs to service_role", schema)
        self.assertIn("grant select on public.review_jobs to authenticated", schema)

    def test_schema_verification_script_checks_ownership_hardening(self) -> None:
        verifier = VERIFY_SCHEMA.read_text(encoding="utf-8").lower()

        self.assertIn("repositories_owner_id_fkey", verifier)
        self.assertIn("confdeltype = 'c'", verifier)
        self.assertIn("repositories_owner_repo_url_unique_idx", verifier)
        self.assertIn("repositories_anonymous_repo_url_unique_idx", verifier)
        self.assertIn("repositories_select_own", verifier)
        self.assertIn("table: review_jobs", verifier)
        self.assertIn("review_jobs_owner_created_idx", verifier)
        self.assertIn("review_jobs_status_updated_idx", verifier)
        self.assertIn("review_jobs_select_own", verifier)
        self.assertIn("privilege: service_role review_jobs read/write", verifier)
        self.assertIn("has_table_privilege('service_role', 'public.review_jobs', 'insert')", verifier)
        self.assertIn("privilege: authenticated review_jobs select", verifier)


if __name__ == "__main__":
    unittest.main()
