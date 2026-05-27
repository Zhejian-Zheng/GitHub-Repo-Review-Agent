from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from repo_review_agent.agent import RepoReviewAgent
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


if __name__ == "__main__":
    unittest.main()
