import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.agent import (
    AgentState,
    RepoReviewAgent,
    _compact_preview,
    _is_helpful_doc_candidate,
)
from repo_review_agent.llm import AIProviderError
from repo_review_agent.report import render_markdown


class RepoReviewAgentTests(unittest.TestCase):
    def test_agent_runs_tool_calling_loop(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "README.md").write_text("# Example\n\nA demo project.\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
            (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")

            report = RepoReviewAgent().run(root)

        self.assertIsNotNone(report.agent_trace)
        tools = [step.tool for step in report.agent_trace or []]
        self.assertEqual(tools[0], "scan_repository")
        self.assertIn("inspect_file", tools)
        self.assertIn("analyze_repository", tools)
        self.assertEqual(tools[-1], "finalize_report")
        self.assertIn("README.md", report.metrics["agent_inspected_files"])
        self.assertIn("pyproject.toml", report.metrics["agent_inspected_files"])

    def test_agent_trace_renders_to_markdown(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            report = RepoReviewAgent().run(root)

        markdown = render_markdown(report)

        self.assertIn("## Agent Trace", markdown)
        self.assertIn("scan_repository", markdown)
        self.assertIn("finalize_report", markdown)

    @patch("repo_review_agent.agent.add_ai_review")
    def test_agent_generates_ai_review_when_configured(self, mock_add_ai_review) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            def attach(report, **kwargs):
                from dataclasses import replace

                from repo_review_agent.models import AIReview

                return replace(
                    report,
                    ai_review=AIReview(
                        provider=kwargs["provider"],
                        model="mock-model",
                        status="generated",
                        summary="ok",
                    ),
                )

            mock_add_ai_review.side_effect = attach
            report = RepoReviewAgent(ai_provider="ollama").run(root)

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.status, "generated")
        self.assertIn("generate_ai_review", [step.tool for step in report.agent_trace or []])

    @patch("repo_review_agent.agent.add_ai_review")
    def test_agent_preserves_report_when_ai_review_fails(self, mock_add_ai_review) -> None:
        mock_add_ai_review.side_effect = AIProviderError("offline")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            report = RepoReviewAgent(ai_provider="ollama").run(root)

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.status, "error")
        self.assertIn("offline", report.ai_review.error)

    @patch("repo_review_agent.agent.add_ai_review")
    def test_agent_can_fail_on_ai_error(self, mock_add_ai_review) -> None:
        mock_add_ai_review.side_effect = AIProviderError("offline")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            with self.assertRaises(AIProviderError):
                RepoReviewAgent(ai_provider="ollama", fail_on_ai_error=True).run(root)

    def test_agent_tool_methods_require_order(self) -> None:
        agent = RepoReviewAgent()
        state = AgentState(root=Path(".").resolve())

        with self.assertRaises(RuntimeError):
            agent._tool_analyze_repository(state, {})

        with self.assertRaises(RuntimeError):
            agent._tool_finalize_report(state, {})

        with self.assertRaises(RuntimeError):
            agent._tool_generate_ai_review(state, {"provider": "ollama"})

    def test_compact_preview_and_doc_candidate_helpers(self) -> None:
        self.assertEqual(_compact_preview("\n\n"), "")
        self.assertEqual(_compact_preview("abcdef", max_chars=5), "ab...")
        self.assertFalse(_is_helpful_doc_candidate("README.md"))
        self.assertFalse(_is_helpful_doc_candidate("docs/example-report.md"))
        self.assertTrue(_is_helpful_doc_candidate("docs/architecture.md"))


if __name__ == "__main__":
    unittest.main()
