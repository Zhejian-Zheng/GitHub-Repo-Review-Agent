import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.cli import main
from repo_review_agent.models import ReviewReport


def minimal_report(repo_name: str = "repo") -> ReviewReport:
    return ReviewReport(
        repo_name=repo_name,
        generated_at="2026-05-28T00:00:00+00:00",
        overview=[],
        metrics={
            "files_scanned": 0,
            "files_skipped": 0,
            "source_files": 0,
            "test_files": 0,
            "dependency_files": 0,
            "ci_files": 0,
        },
        framework_signals={},
        findings=[],
    )


class CLITests(unittest.TestCase):
    def test_main_writes_markdown_and_json_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            output_path = Path(tmp) / "review.md"
            json_path = Path(tmp) / "review.json"
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun python -m unittest.\n\n## Demo\nExample output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

            exit_code = main(
                [
                    str(root),
                    "--output",
                    str(output_path),
                    "--json",
                    str(json_path),
                    "--max-files",
                    "50",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("# Repository Review: repo", output_path.read_text(encoding="utf-8"))
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["repo_name"], "repo")
            self.assertIn("findings", data)

    def test_main_rejects_missing_target_path(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"

            with self.assertRaises(SystemExit):
                main([str(missing)])

    @patch("repo_review_agent.cli.apply_github_issue_mode")
    def test_main_generates_github_issue_dry_run_for_url_target(self, mock_issue_mode) -> None:
        mock_issue_mode.return_value = [{"mode": "dry-run", "repo": "owner/repo"}]

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            with patch("repo_review_agent.cli.resolve_target") as mock_resolve:
                mock_resolve.return_value.__enter__.return_value = root
                mock_resolve.return_value.__exit__.return_value = None

                exit_code = main(
                    [
                        "https://github.com/owner/repo",
                        "--github-issues",
                        "dry-run",
                    ]
                )

        self.assertEqual(exit_code, 0)
        mock_issue_mode.assert_called_once()
        self.assertEqual(mock_issue_mode.call_args.kwargs["repo"], "owner/repo")

    @patch("repo_review_agent.cli.apply_github_pr_comment_mode")
    def test_main_accepts_explicit_github_repo_for_pr_comment(self, mock_comment_mode) -> None:
        mock_comment_mode.return_value = {"mode": "dry-run", "pr_number": 3}

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            exit_code = main(
                [
                    str(root),
                    "--github-repo",
                    "owner/repo",
                    "--github-pr-comment",
                    "3",
                ]
            )

        self.assertEqual(exit_code, 0)
        mock_comment_mode.assert_called_once()
        self.assertEqual(mock_comment_mode.call_args.kwargs["pr_number"], 3)

    @patch("repo_review_agent.cli.apply_github_issue_mode")
    def test_main_exits_on_github_integration_error(self, mock_issue_mode) -> None:
        from repo_review_agent.github import GitHubIntegrationError

        mock_issue_mode.side_effect = GitHubIntegrationError("bad token")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as context:
                main([str(root), "--github-repo", "owner/repo", "--github-issues", "dry-run"])

        self.assertEqual(str(context.exception), "bad token")

    def test_main_requires_github_repo_for_local_issue_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as context:
                main([str(root), "--github-issues", "dry-run"])

        self.assertIn("--github-repo owner/repo is required", str(context.exception))

    @patch("repo_review_agent.cli.add_ai_review")
    def test_main_attaches_ai_error_when_provider_fails(self, mock_add_ai_review) -> None:
        from repo_review_agent.llm import AIProviderError

        mock_add_ai_review.side_effect = AIProviderError("model offline")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            output_path = Path(tmp) / "review.md"
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            exit_code = main(
                [
                    str(root),
                    "--ai-provider",
                    "ollama",
                    "--output",
                    str(output_path),
                ]
            )

            markdown = output_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("AI review was not generated: `model offline`", markdown)

    @patch("repo_review_agent.cli.add_ai_review")
    def test_main_can_fail_on_ai_error(self, mock_add_ai_review) -> None:
        from repo_review_agent.llm import AIProviderError

        mock_add_ai_review.side_effect = AIProviderError("model offline")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as context:
                main([str(root), "--ai-provider", "ollama", "--fail-on-ai-error"])

        self.assertEqual(str(context.exception), "model offline")

    @patch("repo_review_agent.cli.RepoReviewAgent")
    def test_main_runs_custom_agent_mode(self, mock_agent_class) -> None:
        mock_agent_class.return_value.run.return_value = minimal_report()

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            output_path = Path(tmp) / "review.md"

            exit_code = main([str(root), "--agent", "--output", str(output_path)])

        self.assertEqual(exit_code, 0)
        mock_agent_class.assert_called_once()
        mock_agent_class.return_value.run.assert_called_once_with(root.resolve())

    @patch("repo_review_agent.cli.OpenAIFunctionCallingAgent")
    def test_main_runs_function_calling_mode(self, mock_agent_class) -> None:
        mock_agent_class.return_value.run.return_value = minimal_report()

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            output_path = Path(tmp) / "review.md"

            exit_code = main([str(root), "--function-calling", "--output", str(output_path)])

        self.assertEqual(exit_code, 0)
        mock_agent_class.assert_called_once()

    @patch("repo_review_agent.cli.ChatGPTReviewAgent")
    def test_main_runs_chatgpt_agent_mode(self, mock_agent_class) -> None:
        mock_agent_class.return_value.run.return_value = minimal_report()

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            output_path = Path(tmp) / "review.md"

            exit_code = main([str(root), "--chatgpt-agent", "--output", str(output_path)])

        self.assertEqual(exit_code, 0)
        mock_agent_class.assert_called_once()
        mock_agent_class.return_value.run.assert_called_once_with(root.resolve())

    @patch("repo_review_agent.cli.ChatGPTReviewAgent")
    def test_main_exits_when_chatgpt_agent_fails(self, mock_agent_class) -> None:
        from repo_review_agent.llm import AIProviderError

        mock_agent_class.return_value.run.side_effect = AIProviderError("missing key")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()

            with self.assertRaises(SystemExit) as context:
                main([str(root), "--chatgpt-agent"])

        self.assertEqual(str(context.exception), "missing key")

    @patch("repo_review_agent.cli.OpenAIFunctionCallingAgent")
    def test_main_exits_when_function_calling_agent_fails(self, mock_agent_class) -> None:
        from repo_review_agent.llm import AIProviderError

        mock_agent_class.return_value.run.side_effect = AIProviderError("missing key")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()

            with self.assertRaises(SystemExit) as context:
                main([str(root), "--function-calling"])

        self.assertEqual(str(context.exception), "missing key")

    def test_main_requires_github_repo_for_local_pr_comment(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as context:
                main([str(root), "--github-pr-comment", "3"])

        self.assertIn("--github-repo owner/repo is required", str(context.exception))

    @patch("repo_review_agent.cli.subprocess.run")
    def test_resolve_target_clones_git_urls(self, mock_run) -> None:
        from repo_review_agent.cli import resolve_target

        with resolve_target("https://github.com/owner/repo") as repo_path:
            self.assertEqual(repo_path.name, "repo")
            self.assertTrue(str(repo_path.parent).startswith("/tmp/repo-review-"))

        mock_run.assert_called_once()

    def test_looks_like_git_url_accepts_ssh_and_git_syntax(self) -> None:
        from repo_review_agent.cli import _looks_like_git_url

        self.assertTrue(_looks_like_git_url("git@github.com:owner/repo.git"))
        self.assertTrue(_looks_like_git_url("ssh://github.com/owner/repo.git"))
        self.assertFalse(_looks_like_git_url("owner/repo"))


if __name__ == "__main__":
    unittest.main()
