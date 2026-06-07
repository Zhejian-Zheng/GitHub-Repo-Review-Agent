import unittest

from repo_review_agent.models import Finding, ReviewReport
from repo_review_agent.report import render_markdown


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


if __name__ == "__main__":
    unittest.main()
