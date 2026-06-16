from unittest.mock import patch
import unittest

from repo_review_agent.demo import collect_readiness_checks, main, render_readiness_report


COMPLETE_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-key",
    "VITE_SUPABASE_URL": "https://example.supabase.co",
    "VITE_SUPABASE_ANON_KEY": "anon-key",
    "VITE_API_BASE_URL": "https://repo-review-api.onrender.com",
    "REPO_REVIEW_CORS_ORIGINS": "https://zhejian-zheng.github.io",
    "REPO_REVIEW_REQUIRE_AUTH": "true",
    "REPO_REVIEW_ALLOW_LOCAL_TARGETS": "false",
    "REPO_REVIEW_API_TOKEN": "demo-token",
}


class FakeStore:
    def __init__(self, *, supabase_url: str, service_key: str, timeout: float) -> None:
        self.supabase_url = supabase_url
        self.service_key = service_key
        self.timeout = timeout
        self.paths: list[str] = []

    def _request(self, method, path, body=None, *, prefer=None):  # type: ignore[no-untyped-def]
        self.paths.append(path)
        return []


class DemoReadinessTests(unittest.TestCase):
    def test_missing_required_supabase_env_fails(self) -> None:
        checks = collect_readiness_checks({}, check_supabase=False)

        statuses = {check.name: check.status for check in checks}

        self.assertEqual(statuses["SUPABASE_URL"], "fail")
        self.assertEqual(statuses["SUPABASE_ANON_KEY"], "fail")
        self.assertEqual(statuses["SUPABASE_SERVICE_ROLE_KEY"], "fail")

    def test_render_report_summarizes_failures(self) -> None:
        checks = collect_readiness_checks({}, check_supabase=False)

        report = render_readiness_report(checks)

        self.assertIn("[FAIL] SUPABASE_URL", report)
        self.assertIn("Result: not ready", report)

    @patch("repo_review_agent.demo.SupabaseHistoryStore", FakeStore)
    def test_supabase_schema_probe_reads_required_tables(self) -> None:
        checks = collect_readiness_checks(COMPLETE_ENV, check_supabase=True, timeout=3)

        statuses = {check.name: check.status for check in checks}

        self.assertEqual(statuses["table repositories"], "pass")
        self.assertEqual(statuses["table review_runs"], "pass")
        self.assertEqual(statuses["table findings"], "pass")
        self.assertEqual(statuses["table ai_reviews"], "pass")

    @patch.dict("os.environ", COMPLETE_ENV, clear=True)
    @patch("repo_review_agent.demo.SupabaseHistoryStore", FakeStore)
    def test_main_returns_success_when_all_checks_pass(self) -> None:
        exit_code = main([])

        self.assertEqual(exit_code, 0)

    def test_frontend_supabase_mismatch_warns(self) -> None:
        env = {
            **COMPLETE_ENV,
            "VITE_SUPABASE_URL": "https://other.supabase.co",
        }

        checks = collect_readiness_checks(env, check_supabase=False)
        vite_url = next(check for check in checks if check.name == "VITE_SUPABASE_URL")

        self.assertEqual(vite_url.status, "warn")
        self.assertIn("does not match", vite_url.detail)

    def test_split_frontend_warns_when_cors_is_missing(self) -> None:
        env = {
            **COMPLETE_ENV,
            "REPO_REVIEW_CORS_ORIGINS": "",
        }

        checks = collect_readiness_checks(env, check_supabase=False)
        cors = next(check for check in checks if check.name == "REPO_REVIEW_CORS_ORIGINS")

        self.assertEqual(cors.status, "warn")
        self.assertIn("frontend is hosted", cors.detail)


if __name__ == "__main__":
    unittest.main()
