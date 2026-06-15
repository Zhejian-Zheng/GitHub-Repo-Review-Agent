import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.models import AIReview, Finding, ReviewReport
from repo_review_agent.pr_bot import (
    PR_BOT_COMMENT_MARKER,
    blocking_findings,
    build_pr_bot_comment,
    build_pr_review_diff,
    load_report_json,
    main,
    run_pr_bot,
)


def report_with_findings(findings: list[Finding], *, name: str = "repo") -> ReviewReport:
    return ReviewReport(
        repo_name=name,
        generated_at="2026-06-15T00:00:00+00:00",
        overview=["Primary source languages detected: Python (2)."],
        metrics={"files_scanned": 4},
        framework_signals={},
        findings=findings,
        ai_review=AIReview(
            provider="openai",
            model="gpt-test",
            status="generated",
            summary="## AI Architecture Summary\nThe project has a review pipeline.",
        ),
    )


def finding(
    title: str,
    *,
    severity: str = "medium",
    category: str = "testing",
    evidence_paths: list[str] | None = None,
) -> Finding:
    return Finding(
        title=title,
        severity=severity,
        category=category,
        evidence=[f"{title} evidence."],
        evidence_paths=evidence_paths or ["src/app.py"],
        recommendation=f"Fix {title.lower()}.",
    )


class PullRequestBotTests(unittest.TestCase):
    def test_build_pr_review_diff_identifies_new_existing_and_resolved_findings(self) -> None:
        existing = finding("Add tests", evidence_paths=["tests/test_app.py"])
        new = finding("Remove hard-coded secret", severity="high", category="security")
        resolved = finding("Add README detail", severity="low", category="documentation")

        review_diff = build_pr_review_diff(
            report_with_findings([existing, new]),
            report_with_findings([existing, resolved], name="base"),
        )

        self.assertEqual([item.title for item in review_diff.new_findings], ["Remove hard-coded secret"])
        self.assertEqual([item.title for item in review_diff.existing_findings], ["Add tests"])
        self.assertEqual([item.title for item in review_diff.resolved_findings], ["Add README detail"])

    def test_build_pr_bot_comment_focuses_on_new_risks(self) -> None:
        review_diff = build_pr_review_diff(
            report_with_findings([finding("Add tests"), finding("Pin Docker image", severity="high")]),
            report_with_findings([finding("Add tests")]),
        )

        body = build_pr_bot_comment(review_diff, fail_on_severity="high")

        self.assertIn("New findings: `1`", body)
        self.assertIn("Pin Docker image", body)
        self.assertNotIn("Add tests -", body)
        self.assertIn("blocks `high` or higher", body)
        self.assertIn("AI Architecture Summary", body)
        self.assertIn(PR_BOT_COMMENT_MARKER, body)

    def test_blocking_findings_can_gate_new_or_all_findings(self) -> None:
        existing_high = finding("Existing high", severity="high")
        new_low = finding("New low", severity="low", evidence_paths=["README.md"])
        review_diff = build_pr_review_diff(
            report_with_findings([existing_high, new_low]),
            report_with_findings([existing_high]),
        )

        self.assertEqual(blocking_findings(review_diff, fail_on_severity="high", scope="new"), [])
        self.assertEqual(
            [item.title for item in blocking_findings(review_diff, fail_on_severity="high", scope="all")],
            ["Existing high"],
        )

    def test_load_report_json_round_trips_report_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            report = report_with_findings([finding("Add tests")])
            path.write_text(json.dumps(report.to_dict()), encoding="utf-8")

            loaded = load_report_json(path)

        self.assertEqual(loaded.repo_name, "repo")
        self.assertEqual(loaded.findings[0].title, "Add tests")
        self.assertIsNotNone(loaded.ai_review)

    @patch("repo_review_agent.pr_bot.GitHubClient.create_issue_comment")
    def test_run_pr_bot_can_create_comment_and_mark_blocked(self, mock_create_comment) -> None:
        mock_create_comment.return_value = {"html_url": "https://github.com/owner/repo/pull/1#comment"}

        with TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(
                json.dumps(report_with_findings([finding("Remove secret", severity="high")]).to_dict()),
                encoding="utf-8",
            )

            result = run_pr_bot(
                report_json=report_path,
                github_repo="owner/repo",
                pr_number=1,
                comment_mode="create",
                github_token="token",
                fail_on_severity="high",
            )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["comment_action"], "created")
        self.assertEqual(result["comment_url"], "https://github.com/owner/repo/pull/1#comment")
        mock_create_comment.assert_called_once()

    @patch("repo_review_agent.pr_bot.GitHubClient.upsert_issue_comment")
    def test_run_pr_bot_can_upsert_sticky_comment(self, mock_upsert_comment) -> None:
        mock_upsert_comment.return_value = (
            "updated",
            {"html_url": "https://github.com/owner/repo/pull/1#comment"},
        )

        with TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(
                json.dumps(report_with_findings([finding("Add tests")]).to_dict()),
                encoding="utf-8",
            )

            result = run_pr_bot(
                report_json=report_path,
                github_repo="owner/repo",
                pr_number=1,
                comment_mode="upsert",
                github_token="token",
            )

        self.assertFalse(result["blocked"])
        self.assertEqual(result["comment_action"], "updated")
        self.assertEqual(result["comment_url"], "https://github.com/owner/repo/pull/1#comment")
        mock_upsert_comment.assert_called_once()

    def test_main_exits_nonzero_when_threshold_is_hit(self) -> None:
        with TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(
                json.dumps(report_with_findings([finding("Remove secret", severity="high")]).to_dict()),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit) as context:
                main(
                    [
                        "--report-json",
                        str(report_path),
                        "--comment-mode",
                        "none",
                        "--fail-on-severity",
                        "high",
                    ]
                )

        self.assertIn("blocked CI", str(context.exception))


if __name__ == "__main__":
    unittest.main()
