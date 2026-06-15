import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.mcp_server import (
    _run_review_for_path,
    create_mcp_server,
    issue_drafts_from_report_dict,
    run_review_target,
)


class MCPServerHelpersTests(unittest.TestCase):
    def test_issue_drafts_from_report_dict(self) -> None:
        drafts = issue_drafts_from_report_dict(
            {
                "repo_name": "example",
                "generated_at": "2026-05-27T00:00:00+00:00",
                "overview": [],
                "metrics": {},
                "framework_signals": {},
                "findings": [
                    {
                        "title": "Add tests",
                        "severity": "medium",
                        "category": "testing",
                        "evidence": ["No tests found."],
                        "recommendation": "Add unit tests.",
                        "evidence_paths": ["src/app.py"],
                    }
                ],
            }
        )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].title, "[MEDIUM] Add tests")
        self.assertIn("`src/app.py`", drafts[0].body)

    def test_run_review_for_path_supports_direct_and_rejects_unknown_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            report = _run_review_for_path(root, mode="direct", max_files=50, max_file_size=512_000)

            self.assertEqual(report.repo_name, root.name)
            with self.assertRaises(ValueError):
                _run_review_for_path(root, mode="bad", max_files=50, max_file_size=512_000)

    def test_run_review_target_returns_markdown_and_report(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            result = run_review_target(str(root), mode="direct")

        self.assertIn("markdown", result)
        self.assertEqual(result["report"]["repo_name"], Path(tmp).name)

    def test_create_mcp_server_registers_tools(self) -> None:
        class DummyMCP:
            def __init__(self, name, instructions):
                self.name = name
                self.instructions = instructions
                self.tools = {}
                self.ran = False

            def tool(self):
                def decorator(func):
                    self.tools[func.__name__] = func
                    return func

                return decorator

            def run(self):
                self.ran = True

        with patch("repo_review_agent.mcp_server.FastMCP", DummyMCP):
            server = create_mcp_server()

        self.assertEqual(server.name, "GitHub Repo Review Agent")
        self.assertIn("review_repository", server.tools)
        self.assertIn("generate_issue_backlog", server.tools)
        self.assertIn("summarize_architecture", server.tools)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            review = server.tools["review_repository"](str(root), mode="direct")
            issues = server.tools["generate_issue_backlog"](str(root), mode="direct")
            summary = server.tools["summarize_architecture"](str(root), mode="direct")

        self.assertIn("markdown", review)
        self.assertTrue(issues)
        self.assertIn("repo_name", summary)

    def test_create_mcp_server_requires_dependency(self) -> None:
        with (
            patch("repo_review_agent.mcp_server.FastMCP", None),
            self.assertRaises(RuntimeError),
        ):
            create_mcp_server()

    def test_main_runs_created_server(self) -> None:
        from repo_review_agent import mcp_server

        class DummyServer:
            def __init__(self):
                self.ran = False

            def run(self):
                self.ran = True

        server = DummyServer()
        with patch.object(mcp_server, "create_mcp_server", return_value=server):
            mcp_server.main()

        self.assertTrue(server.ran)


if __name__ == "__main__":
    unittest.main()
