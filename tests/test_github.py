from unittest.mock import patch
import unittest

from repo_review_agent.github import (
    GitHubClient,
    GitHubIntegrationError,
    apply_github_issue_mode,
    apply_github_pr_comment_mode,
    build_pr_comment_body,
    issue_drafts_from_report,
    parse_github_repo,
)
from repo_review_agent.models import Finding, ReviewReport


def sample_report() -> ReviewReport:
    return ReviewReport(
        repo_name="example",
        generated_at="2026-05-27T00:00:00+00:00",
        overview=["No CI workflow files were detected."],
        metrics={},
        framework_signals={},
        findings=[
            Finding(
                title="Add a CI workflow",
                severity="medium",
                category="delivery",
                evidence=["No workflow file was found."],
                recommendation="Run tests on pull requests using GitHub Actions.",
            ),
            Finding(
                title="No major project hygiene gaps detected",
                severity="info",
                category="summary",
                evidence=["README was present."],
                recommendation="Continue improving coverage.",
            ),
        ],
    )


class GitHubIntegrationTests(unittest.TestCase):
    def test_parse_github_repo(self) -> None:
        self.assertEqual(parse_github_repo("owner/repo"), "owner/repo")
        self.assertEqual(parse_github_repo("https://github.com/owner/repo.git"), "owner/repo")
        self.assertEqual(parse_github_repo("https://github.com/owner/repo/pull/1"), "owner/repo")
        self.assertIsNone(parse_github_repo("https://example.com/owner/repo"))

    def test_issue_drafts_from_report_skips_info_findings(self) -> None:
        drafts = issue_drafts_from_report(sample_report())

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].title, "[MEDIUM] Add a CI workflow")
        self.assertIn("No workflow file was found.", drafts[0].body)

    def test_issue_dry_run_returns_drafts(self) -> None:
        result = apply_github_issue_mode(
            report=sample_report(),
            repo="owner/repo",
            mode="dry-run",
        )

        self.assertEqual(result[0]["mode"], "dry-run")
        self.assertEqual(result[0]["repo"], "owner/repo")

    def test_pr_comment_dry_run_contains_summary(self) -> None:
        result = apply_github_pr_comment_mode(
            report=sample_report(),
            repo="owner/repo",
            pr_number=12,
            mode="dry-run",
        )

        self.assertEqual(result["pr_number"], 12)
        self.assertIn("Repository Review Agent", result["body"])
        self.assertIn("Add a CI workflow", result["body"])

    def test_build_pr_comment_body_reports_no_actionable_findings(self) -> None:
        report = ReviewReport(
            repo_name="example",
            generated_at="2026-05-27T00:00:00+00:00",
            overview=["Looks healthy."],
            metrics={},
            framework_signals={},
            findings=[
                Finding(
                    title="No major project hygiene gaps detected",
                    severity="info",
                    category="summary",
                    evidence=["README was present."],
                    recommendation="Continue improving coverage.",
                )
            ],
        )

        body = build_pr_comment_body(report)

        self.assertIn("No immediate issue suggestions.", body)

    def test_create_mode_requires_token(self) -> None:
        with self.assertRaises(GitHubIntegrationError):
            GitHubClient(token=None).create_issue("owner/repo", issue_drafts_from_report(sample_report())[0])

    @patch("repo_review_agent.github.GitHubClient.create_issue")
    def test_create_issue_mode_uses_client(self, mock_create_issue) -> None:
        mock_create_issue.return_value = {"html_url": "https://github.com/owner/repo/issues/1", "number": 1}

        result = apply_github_issue_mode(
            report=sample_report(),
            repo="owner/repo",
            mode="create",
            token="test-token",
        )

        self.assertEqual(result[0]["number"], 1)
        mock_create_issue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
