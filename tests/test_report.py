import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.models import AgentStep, AIReview, Finding, ReviewReport
from repo_review_agent.report import render_markdown, write_json, write_markdown


class ReportRenderingTests(unittest.TestCase):
    def test_render_markdown_supports_chinese(self) -> None:
        report = ReviewReport(
            repo_name="example",
            generated_at="2026-05-28T00:00:00+00:00",
            overview=["Primary source languages detected: Python (2)."],
            metrics={
                "files_scanned": 4,
                "files_skipped": 0,
                "source_files": 2,
                "test_files": 0,
                "dependency_files": 1,
                "ci_files": 0,
                "languages": {"Python": 2},
            },
            framework_signals={},
            findings=[
                Finding(
                    title="Add automated tests for the core behavior",
                    severity="medium",
                    category="testing",
                    evidence=["2 source file(s) found, but no tests were detected."],
                    recommendation="Add small tests around the scanner and analyzer so regressions are caught before release.",
                    evidence_paths=["src/app.py"],
                )
            ],
        )

        markdown = render_markdown(report, language="zh-CN")

        self.assertIn("# 仓库评审: example", markdown)
        self.assertIn("## 执行摘要", markdown)
        self.assertIn("检测到主要源码语言", markdown)
        self.assertIn("为核心行为添加自动化测试", markdown)
        self.assertIn("## GitHub Issue 待办", markdown)
        self.assertIn("证据文件", markdown)
        self.assertIn("`src/app.py`", markdown)

    def test_render_markdown_includes_ai_error_and_no_issue_backlog(self) -> None:
        report = ReviewReport(
            repo_name="healthy",
            generated_at="2026-05-28T00:00:00+00:00",
            overview=["No application source files were detected in the scanned sample."],
            metrics={
                "files_scanned": 1,
                "files_skipped": 0,
                "source_files": 0,
                "test_files": 0,
                "dependency_files": 0,
                "ci_files": 0,
                "languages": {},
            },
            framework_signals={},
            findings=[
                Finding(
                    title="No major project hygiene gaps detected",
                    severity="info",
                    category="summary",
                    evidence=["README was present."],
                    recommendation="Keep improving.",
                )
            ],
            ai_review=AIReview(
                provider="openai",
                model="gpt-test",
                status="error",
                summary="",
                error="boom",
            ),
            agent_trace=[
                AgentStep(
                    thought="Think",
                    tool="scan_repository",
                    tool_input={"path": "."},
                    observation="Done",
                )
            ],
        )

        markdown = render_markdown(report)

        self.assertIn("AI review was not generated: `boom`", markdown)
        self.assertIn("- Languages: `none detected`", markdown)
        self.assertIn("- No immediate issue suggestions.", markdown)
        self.assertIn("### Step 1: `scan_repository`", markdown)

    def test_write_json_and_markdown_outputs(self) -> None:
        report = ReviewReport(
            repo_name="example",
            generated_at="2026-05-28T00:00:00+00:00",
            overview=["No dependency manifest was found."],
            metrics={
                "files_scanned": 1,
                "files_skipped": 0,
                "source_files": 0,
                "test_files": 0,
                "dependency_files": 0,
                "ci_files": 0,
            },
            framework_signals={"FastAPI": ["pyproject.toml: fastapi"]},
            findings=[],
        )

        with TemporaryDirectory() as tmp:
            markdown_path = Path(tmp) / "report.md"
            json_path = Path(tmp) / "report.json"

            write_markdown(report, markdown_path)
            write_json(report, json_path)

            self.assertIn("**FastAPI**", markdown_path.read_text(encoding="utf-8"))
            self.assertIn('"repo_name": "example"', json_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
