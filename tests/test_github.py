import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from repo_review_agent.github import (
    GitHubClient,
    GitHubIntegrationError,
    IssueDraft,
    apply_github_issue_mode,
    apply_github_pr_comment_mode,
    build_pr_comment_body,
    issue_draft_from_finding,
    issue_drafts_from_report,
    parse_github_repo,
)
from repo_review_agent.models import AIReview, Finding, ReviewReport


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
                evidence_paths=["src/app.py"],
            ),
            Finding(
                title="No major project hygiene gaps detected",
                severity="info",
                category="summary",
                evidence=["README was present."],
                recommendation="Continue improving coverage.",
                evidence_paths=["README.md"],
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
        self.assertIn("Evidence Files", drafts[0].body)
        self.assertIn("`src/app.py`", drafts[0].body)

    def test_issue_draft_from_finding_handles_empty_evidence(self) -> None:
        draft = issue_draft_from_finding(
            Finding(
                title="Check manually",
                severity="low",
                category="review",
                evidence=[],
                recommendation="Inspect the repository.",
                evidence_paths=[],
            )
        )

        self.assertIn("- No evidence listed.", draft.body)
        self.assertIn("- No evidence files listed.", draft.body)

    def test_issue_draft_to_dict(self) -> None:
        self.assertEqual(
            IssueDraft("Title", "Body", ["bug"]).to_dict(),
            {"title": "Title", "body": "Body", "labels": ["bug"]},
        )

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
        self.assertIn("Files: `src/app.py`.", result["body"])

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
                    evidence_paths=["README.md"],
                )
            ],
        )

        body = build_pr_comment_body(report)

        self.assertIn("No immediate issue suggestions.", body)

    def test_build_pr_comment_body_includes_generated_ai_review(self) -> None:
        report = sample_report()
        report = ReviewReport(
            **{
                **report.to_dict(),
                "findings": report.findings,
                "ai_review": AIReview(
                    provider="ollama",
                    model="llama",
                    status="generated",
                    summary="## AI Architecture Summary\nLooks solid.",
                ),
            }
        )

        body = build_pr_comment_body(report)

        self.assertIn("### AI Review", body)
        self.assertIn("Looks solid.", body)

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

    @patch("repo_review_agent.github.GitHubClient.create_issue_comment")
    def test_create_pr_comment_mode_uses_client(self, mock_create_comment) -> None:
        mock_create_comment.return_value = {"html_url": "https://github.com/owner/repo/pull/12#comment"}

        result = apply_github_pr_comment_mode(
            report=sample_report(),
            repo="owner/repo",
            pr_number=12,
            mode="create",
            token="test-token",
        )

        self.assertEqual(result["html_url"], "https://github.com/owner/repo/pull/12#comment")
        mock_create_comment.assert_called_once()

    def test_unknown_github_modes_return_empty_results(self) -> None:
        self.assertEqual(
            apply_github_issue_mode(report=sample_report(), repo="owner/repo", mode="skip"),
            [],
        )
        self.assertEqual(
            apply_github_pr_comment_mode(
                report=sample_report(),
                repo="owner/repo",
                pr_number=1,
                mode="skip",
            ),
            {},
        )

    @patch("repo_review_agent.github.urlopen")
    def test_github_client_request_json_success_and_errors(self, mock_urlopen) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"html_url":"https://example.test","number":7}'
        mock_urlopen.return_value = response

        client = GitHubClient(token="token", api_url="https://api.example.test", timeout=1)
        result = client.create_issue("owner/repo", issue_drafts_from_report(sample_report())[0])

        self.assertEqual(result["number"], 7)

        mock_urlopen.side_effect = HTTPError(
            "https://api.example.test",
            422,
            "invalid",
            {},
            BytesIO(b'{"message":"bad"}'),
        )
        with self.assertRaises(GitHubIntegrationError):
            client.create_issue("owner/repo", issue_drafts_from_report(sample_report())[0])

        mock_urlopen.side_effect = URLError("offline")
        with self.assertRaises(GitHubIntegrationError):
            client.create_issue("owner/repo", issue_drafts_from_report(sample_report())[0])

        invalid_json_response = MagicMock()
        invalid_json_response.__enter__.return_value.read.return_value = b"not-json"
        mock_urlopen.side_effect = None
        mock_urlopen.return_value = invalid_json_response
        with self.assertRaises(GitHubIntegrationError):
            client.create_issue("owner/repo", issue_drafts_from_report(sample_report())[0])

        unexpected_response = MagicMock()
        unexpected_response.__enter__.return_value.read.return_value = b"[]"
        mock_urlopen.return_value = unexpected_response
        with self.assertRaises(GitHubIntegrationError):
            client.create_issue("owner/repo", issue_drafts_from_report(sample_report())[0])


if __name__ == "__main__":
    unittest.main()
