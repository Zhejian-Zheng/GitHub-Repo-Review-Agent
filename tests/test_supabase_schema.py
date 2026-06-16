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

    def test_schema_verification_script_checks_ownership_hardening(self) -> None:
        verifier = VERIFY_SCHEMA.read_text(encoding="utf-8").lower()

        self.assertIn("repositories_owner_id_fkey", verifier)
        self.assertIn("confdeltype = 'c'", verifier)
        self.assertIn("repositories_owner_repo_url_unique_idx", verifier)
        self.assertIn("repositories_anonymous_repo_url_unique_idx", verifier)
        self.assertIn("repositories_select_own", verifier)


if __name__ == "__main__":
    unittest.main()
