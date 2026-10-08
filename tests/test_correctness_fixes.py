import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from repo_review_agent import web
from repo_review_agent.auth import AuthUser
from repo_review_agent.config import ReviewConfig, apply_review_config
from repo_review_agent.history import HistoryStoreError
from repo_review_agent.linters import ruff_findings
from repo_review_agent.models import Finding, ReviewReport
from repo_review_agent.service import run_review


class CorrectnessTests(unittest.TestCase):
    def test_ruff_cannot_fix_or_suppress_diagnostics_using_repository_config(self):
        executable = shutil.which("ruff") or str(Path(".venv/bin/ruff").resolve())
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app.py"
            source.write_text('import os\n\nprint("hello")\n')
            before = source.read_bytes()
            for config in [
                "fix = true\n",
                "fix = true\nfix-only = true\n",
                '[lint]\nignore = ["F401"]\n',
            ]:
                with self.subTest(config=config):
                    source.write_bytes(before)
                    (root / "ruff.toml").write_text(config)
                    with patch("repo_review_agent.linters.shutil.which", return_value=executable):
                        findings = ruff_findings(root)
                    self.assertEqual(source.read_bytes(), before)
                    self.assertTrue(any("F401" in f.title for f in findings))

    def test_failed_linter_is_visible_not_a_clean_scan(self):
        with patch("repo_review_agent.linters.shutil.which", return_value=None):
            findings = ruff_findings(Path("."))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "tool.ruff.unavailable")
        self.assertEqual(findings[0].severity, "info")

    def test_history_routes_hide_storage_details(self):
        store = web.InMemoryReviewJobStore()
        self.addCleanup(store.shutdown)
        with patch.object(web, "build_review_job_store", return_value=store):
            app = web.create_app()
        for path, args in [
            ("/history/repositories", []),
            ("/history/repositories/{repository_id}", ["repo"]),
            (
                "/history/repositories/{repository_id}/findings/{fingerprint}/feedback",
                ["repo", "fp", web.FindingFeedbackRequest(status="ignored")],
            ),
        ]:
            endpoint = next(r.endpoint for r in app.routes if r.path == path)
            with (
                self.subTest(path=path),
                patch.object(
                    web, "authenticated_user_from_request", return_value=AuthUser("owner")
                ),
                patch.object(
                    web.SupabaseHistoryStore,
                    "from_env",
                    side_effect=HistoryStoreError("INTERNAL DATABASE DETAIL"),
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    endpoint(SimpleNamespace(), *args)
                self.assertEqual(caught.exception.status_code, 503)
                self.assertNotIn("INTERNAL", caught.exception.detail)

    def test_untrusted_root_policy_cannot_hide_scan(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text('print("hello")')
            baseline = run_review(root, mode="direct")
            (root / ".repo-review.json").write_text(
                json.dumps(
                    {
                        "ignore": ["*"],
                        "disabled_categories": list({f.category for f in baseline.findings}),
                    }
                )
            )
            for mode in ["direct", "agent"]:
                with self.subTest(mode=mode):
                    result = run_review(root, mode=mode)
                    self.assertGreater(result.metrics["source_files"], 0)
                    self.assertGreater(len(result.findings), 0)
            trusted = run_review(root, mode="direct", trust_repository_config=True)
            self.assertEqual(trusted.metrics["source_files"], 0)

    def test_policy_retains_original_findings_and_stable_identity(self):
        from repo_review_agent.findings import finding_fingerprint

        original = Finding(
            "Risk", "high", "security", ["api_key=sk-" + "a" * 36], "Fix", rule_id="rule"
        )
        report = ReviewReport("repo", "", [], {}, {}, [original])
        config = ReviewConfig(severity_overrides={"rule": "low"})
        adjusted = apply_review_config(report, config)
        self.assertEqual(adjusted.raw_findings[0].severity, "high")
        self.assertEqual(finding_fingerprint(adjusted.findings[0]), finding_fingerprint(original))
        suppressed = apply_review_config(adjusted, ReviewConfig(disabled_rules=["rule"]))
        self.assertEqual(suppressed.findings, [])
        self.assertEqual(suppressed.raw_findings[0].severity, "high")
        self.assertNotIn("sk-" + "a" * 36, json.dumps(suppressed.to_dict()))
        self.assertEqual(
            apply_review_config(suppressed, ReviewConfig(disabled_rules=["rule"])).raw_findings,
            suppressed.raw_findings,
        )

    def test_feedback_input_error_is_not_a_storage_outage(self):
        from datetime import datetime

        from repo_review_agent.history import SupabaseHistoryStore

        store = web.InMemoryReviewJobStore()
        self.addCleanup(store.shutdown)
        with patch.object(web, "build_review_job_store", return_value=store):
            app = web.create_app()
        route = next(
            r.endpoint for r in app.routes if r.path.endswith("/findings/{fingerprint}/feedback")
        )
        storage = SupabaseHistoryStore(supabase_url="unused", service_key="unused")
        with (
            patch.object(web, "authenticated_user_from_request", return_value=AuthUser("owner")),
            patch.object(web.SupabaseHistoryStore, "from_env", return_value=storage),
            self.assertRaises(HTTPException) as caught,
        ):
            route(
                SimpleNamespace(),
                "repo",
                "fp",
                web.FindingFeedbackRequest(status="ignored", expires_at=datetime(2030, 1, 1)),
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_policy_audit_survives_report_json_round_trip(self):
        from repo_review_agent.pr_bot import load_report_json

        original = ReviewReport(
            "repo", "", [], {}, {}, [Finding("Risk", "high", "security", ["bad"], "Fix")]
        )
        reviewed = apply_review_config(original, ReviewConfig(disabled_categories=["security"]))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps(reviewed.to_dict()))
            restored = load_report_json(path)
        self.assertEqual(restored.raw_findings, reviewed.raw_findings)
        self.assertEqual(restored.policy_decisions, reviewed.policy_decisions)
