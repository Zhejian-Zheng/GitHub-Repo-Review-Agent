import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from repo_review_agent import findings as lifecycle
from repo_review_agent.github import issue_drafts_from_report
from repo_review_agent.history import HistoryNotFoundError, SupabaseHistoryStore
from repo_review_agent.models import AIReview, Finding, ReviewReport
from repo_review_agent.pr_bot import blocking_findings, build_pr_review_diff, load_report_json


def report():
    return ReviewReport(
        "repo",
        "",
        [],
        {},
        {},
        [Finding("Tests", "low", "testing", ["No tests"], "Add tests", ["tests/test_db.py"])],
        AIReview(
            "openai",
            "test",
            "generated",
            "summary",
            findings=[
                dict(
                    title="Unsafe SQL",
                    severity="high",
                    path="src/db.py",
                    start_line=8,
                    end_line=9,
                    evidence="query = raw\nrun(query)",
                    confidence=0.95,
                    recommendation="Bind arguments",
                )
            ],
        ),
    )


class Store(SupabaseHistoryStore):
    def __init__(self, owned=True):
        super().__init__(supabase_url="https://example.com", service_key="test")
        self.owned = owned
        self.rows = []
        self.calls = []

    def _request(self, method, path, body=None, *, prefer=None):
        self.calls.append((method, path, body))
        if path.startswith("repositories"):
            return [{"id": "repo-id"}] if self.owned else []
        if path.startswith("review_runs?"):
            return [{"id": "run-id"}]
        if path.startswith("findings?"):
            return self.rows
        if path.startswith("finding_feedback"):
            if method == "POST":
                self.feedback = body
                return body
            return getattr(self, "feedback", [])
        if path == "review_runs":
            return [{"id": "run-id"}]
        if path == "findings":
            self.rows = body
        return []


class LifecycleTests(unittest.TestCase):
    def test_ai_evidence_survives_canonical_json_round_trip_and_blocks(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        original = report()
        items = lifecycle.review_findings(original)
        assert len(items) == 2
        assert items[1].source == "ai"
        assert items[1].evidence == ["query = raw\nrun(query)"]
        assert (items[1].path, items[1].start_line, items[1].end_line, items[1].confidence) == (
            "src/db.py",
            8,
            9,
            0.95,
        )
        path = tmp_path / "report.json"
        path.write_text(json.dumps(original.to_dict()))
        restored = load_report_json(path)
        assert len(lifecycle.review_findings(restored)) == 2
        assert len(blocking_findings(build_pr_review_diff(restored), fail_on_severity="high")) == 1
        assert len(issue_drafts_from_report(restored)) == 2

    def test_feedback_expires_and_preserves_raw_evidence(self):
        original = report()
        fingerprint = lifecycle.finding_fingerprint(lifecycle.review_findings(original)[1])
        feedback = [
            dict(
                fingerprint=fingerprint,
                status="ignored",
                reason="Accepted risk",
                expires_at="2026-10-06T00:00:00Z",
            )
        ]
        reviewed = replace(original, finding_feedback=feedback)
        assert (
            len(
                lifecycle.effective_findings(
                    reviewed, now=datetime(2026, 10, 5, tzinfo=timezone.utc)
                )
            )
            == 1
        )
        assert (
            len(
                lifecycle.effective_findings(
                    reviewed, now=datetime(2026, 10, 6, tzinfo=timezone.utc)
                )
            )
            == 2
        )
        assert len(reviewed.to_dict()["findings"]) == 2
        assert (
            len(
                issue_drafts_from_report(
                    replace(
                        reviewed,
                        finding_feedback=[dict(fingerprint=fingerprint, status="false_positive")],
                    )
                )
            )
            == 1
        )

    def test_feedback_cannot_write_to_unowned_repository(self):
        store = Store(owned=False)
        try:
            store.set_finding_feedback(
                repository_id="repo-id", fingerprint="abc", owner_id="stranger", status="ignored"
            )
        except HistoryNotFoundError:
            pass
        else:
            raise AssertionError("Ownership was not enforced")
        assert not any(method == "POST" for method, _, _ in store.calls)


class IncrementalTests(unittest.TestCase):
    def test_changed_added_lines_control_annotations_and_incremental_gate(self):
        from repo_review_agent import pr_bot

        files = [
            dict(
                filename="src/db.py",
                status="modified",
                patch="@@ -7,2 +7,3 @@\n context\n-old\n+query = raw\n+run(query)",
            )
        ]
        self.assertTrue(hasattr(pr_bot, "build_pr_annotations"), "Missing annotation builder")
        annotations = pr_bot.build_pr_annotations(report(), files)
        self.assertEqual(
            annotations,
            [
                dict(
                    path="src/db.py",
                    start_line=8,
                    end_line=9,
                    annotation_level="failure",
                    title="Unsafe SQL",
                    message="Bind arguments\n\nquery = raw\nrun(query)",
                )
            ],
        )
        self.assertEqual(
            pr_bot.build_pr_annotations(
                report(), [dict(filename="src/db.py", patch="@@ -1 +1 @@\n-x\n+y")]
            ),
            [],
        )
        self.assertEqual(pr_bot.build_pr_annotations(report(), [dict(filename="src/db.py")]), [])
        diff = pr_bot.build_pr_review_diff(report(), changed_files=files)
        self.assertEqual([item.title for item in diff.new_findings], ["Unsafe SQL"])
        self.assertEqual(blocking_findings(diff, fail_on_severity="high")[0].path, "src/db.py")

    def test_check_annotations_are_batched_without_losing_evidence(self):
        from unittest.mock import patch

        from repo_review_agent.github import GitHubClient

        annotations = [
            dict(
                path="app.py", start_line=i, end_line=i, annotation_level="warning", message="Risk"
            )
            for i in range(1, 52)
        ]
        client = GitHubClient(token="test")
        self.assertTrue(hasattr(client, "create_annotated_check"), "Missing check writer")
        with patch.object(
            client, "_request_dict", return_value={"id": 7, "html_url": "https://example.com/check"}
        ) as request:
            result = client.create_annotated_check(
                "owner/repo",
                head_sha="a" * 40,
                annotations=annotations,
                summary="Review",
                conclusion="failure",
            )
        self.assertEqual(result["id"], 7)
        self.assertEqual(
            request.call_args_list[0].args[:2], ("POST", "/repos/owner/repo/check-runs")
        )
        self.assertEqual(
            request.call_args_list[0].args[2]["output"]["annotations"], annotations[:50]
        )
        self.assertEqual(
            request.call_args_list[1].args[:2], ("PATCH", "/repos/owner/repo/check-runs/7")
        )
        self.assertEqual(
            request.call_args_list[1].args[2]["output"]["annotations"], annotations[50:]
        )

    def test_job_cancellation_is_owned_and_enqueue_has_daily_quota(self):
        from unittest.mock import patch

        from repo_review_agent.history import SupabaseReviewJobStore

        store = SupabaseReviewJobStore(supabase_url="https://example.com", service_key="test")
        self.assertTrue(hasattr(store, "request_cancel"), "Missing cancellation RPC")
        with patch.object(
            store, "_request", return_value=[{"id": "job", "status": "cancelled"}]
        ) as request:
            row = store.request_cancel("job", owner_id="owner")
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(
            request.call_args.args,
            ("POST", "rpc/cancel_review_job", {"p_job": "job", "p_owner": "owner"}),
        )
        with patch.object(store, "_request", return_value=[]) as request:
            store.enqueue_job(
                target="owner/repo",
                request_payload={},
                owner_id="owner",
                max_pending=10,
                per_user_limit=2,
                daily_limit=5,
            )
        self.assertEqual(request.call_args.args[2]["p_daily_limit"], 5)


class FeedbackValidationTests(unittest.TestCase):
    def test_invalid_feedback_is_rejected_before_database_mutation(self):
        from repo_review_agent.history import HistoryStoreError

        store = Store()
        for data in [
            dict(status="deleted"),
            dict(status="ignored", expires_at="2026-10-05T00:00:00"),
            dict(status="ignored", expires_at="2026-10-05T00:00:00+08:00"),
        ]:
            with self.subTest(data=data), self.assertRaises(HistoryStoreError):
                store.set_finding_feedback(
                    repository_id="repo-id", fingerprint="abc", owner_id="user", **data
                )
        self.assertFalse(any(method == "POST" for method, _, _ in store.calls))

    def test_same_ai_code_keeps_fingerprint_when_line_number_moves(self):
        first = lifecycle.review_findings(report())[1]
        moved = replace(first, start_line=20, end_line=21, fingerprint=None)
        changed = replace(first, evidence=["different code"], fingerprint=None)
        self.assertEqual(lifecycle.finding_fingerprint(first), lifecycle.finding_fingerprint(moved))
        self.assertNotEqual(
            lifecycle.finding_fingerprint(first), lifecycle.finding_fingerprint(changed)
        )

    def test_incremental_all_scope_does_not_block_unchanged_file_risks(self):
        current = replace(
            report(),
            findings=[Finding("Elsewhere", "high", "code", ["other"], "fix", ["other.py"])],
        )
        diff = build_pr_review_diff(current, changed_files=[dict(filename="new.py")])
        self.assertEqual(blocking_findings(diff, fail_on_severity="high", scope="all"), [])


class FingerprintTests(unittest.TestCase):
    def test_shared_rule_id_does_not_collapse_different_dependency_targets(self):
        findings = [
            Finding(
                title,
                "high",
                "dependency vulnerabilities",
                ["vulnerable"],
                "upgrade",
                ["package-lock.json"],
                rule_id="dependency.osv",
            )
            for title in ["lodash@1 is vulnerable", "react@1 is vulnerable"]
        ]
        current = replace(report(), findings=findings, ai_review=None)
        self.assertEqual(len(lifecycle.review_findings(current)), 2)


class PostingValidationTests(unittest.TestCase):
    def test_invalid_annotation_request_does_not_post_summary_first(self):
        from unittest.mock import patch

        from repo_review_agent.github import GitHubIntegrationError
        from repo_review_agent.pr_bot import run_pr_bot

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report().to_dict()))
            with patch("repo_review_agent.pr_bot.GitHubClient.create_issue_comment") as post:
                with self.assertRaises(GitHubIntegrationError):
                    run_pr_bot(
                        report_json=path,
                        github_repo="owner/repo",
                        pr_number=1,
                        comment_mode="create",
                        annotation_mode="create",
                    )
                post.assert_not_called()
