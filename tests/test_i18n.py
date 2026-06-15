import unittest

from repo_review_agent.i18n import (
    ai_section_headings,
    language_display_name,
    localize_report,
    normalize_report_language,
)
from repo_review_agent.models import AgentStep, AIReview, Finding, ReviewReport


class I18nTests(unittest.TestCase):
    def test_language_helpers_normalize_common_aliases(self) -> None:
        self.assertEqual(normalize_report_language(None), "en")
        self.assertEqual(normalize_report_language("English"), "en")
        self.assertEqual(normalize_report_language("zh_CN"), "zh-CN")
        self.assertEqual(normalize_report_language("mystery"), "en")
        self.assertEqual(language_display_name("zh"), "Simplified Chinese")
        self.assertEqual(ai_section_headings("cn")[0], "## AI 架构总结")

    def test_localize_report_translates_overview_findings_ai_and_trace(self) -> None:
        report = ReviewReport(
            repo_name="example",
            generated_at="2026-05-28T00:00:00+00:00",
            overview=[
                "Primary source languages detected: Python (2).",
                "Dependency manifests found: pyproject.toml.",
                "Test coverage surface detected through 3 test file(s).",
                "CI configuration detected: .github/workflows/ci.yml.",
                "Framework and tooling signals: FastAPI.",
                "No application source files were detected in the scanned sample.",
                "No dependency manifest was found.",
                "No test files were detected.",
                "No CI workflow files were detected.",
                "Custom sentence.",
            ],
            metrics={},
            framework_signals={},
            findings=[
                Finding(
                    title="Add a README with setup and usage instructions",
                    severity="high",
                    category="documentation",
                    evidence=[
                        "2 source file(s) found, but no tests were detected.",
                        "Only 1 test file(s) were found for 8 source file(s).",
                        "README.md is missing setup or usage instructions, example output, demo, or screenshots.",
                        "CI files were found (.github/workflows/ci.yml), but no common test command was detected.",
                        "Dockerfile does not set a non-root USER before runtime.",
                        "4 file(s) were skipped because of limits or read errors.",
                        "app.py: secret-like value matched 'token'",
                        "README.md was not found.",
                        "Unknown evidence.",
                    ],
                    recommendation="Add a concise README that explains the project goal, setup steps, commands, and sample output.",
                    evidence_paths=["README.md"],
                ),
                Finding(
                    title="Unknown title",
                    severity="low",
                    category="unknown",
                    evidence=["Unknown evidence."],
                    recommendation="Unknown recommendation.",
                ),
            ],
            ai_review=AIReview(
                provider="openai",
                model="gpt-test",
                status="error",
                summary="",
                error="OPENAI_API_KEY is not set.",
            ),
            agent_trace=[
                AgentStep(
                    thought="I need a structured map of the repository before making review decisions.",
                    tool="scan_repository",
                    tool_input={},
                    observation="Scanned 4 file(s), found 2 source file(s), 1 test file(s), and 1 CI file(s).",
                ),
                AgentStep(
                    thought="I should inspect important project files before producing risk findings.",
                    tool="inspect_file",
                    tool_input={},
                    observation="Inspected README.md: 5 line(s). Preview: # Example",
                ),
                AgentStep(
                    thought="I have enough repository context to run deterministic risk analysis.",
                    tool="analyze_repository",
                    tool_input={},
                    observation="Generated 2 finding(s) after inspecting 1 key file(s).",
                ),
                AgentStep(
                    thought="The structured findings are ready, so I can ask the selected model to synthesize the review.",
                    tool="generate_ai_review",
                    tool_input={},
                    observation="Generated AI review with ollama/llama3.2.",
                ),
                AgentStep(
                    thought="The review report is complete and should be rendered for the user.",
                    tool="finalize_report",
                    tool_input={},
                    observation="Rendered Markdown preview with 100 character(s).",
                ),
                AgentStep(
                    thought="Other thought.",
                    tool="inspect_file",
                    tool_input={},
                    observation="Inspected empty.txt: file was empty or unreadable.",
                ),
                AgentStep(
                    thought="Other thought.",
                    tool="generate_ai_review",
                    tool_input={},
                    observation="AI review failed but the agent preserved the base report: OPENAI_API_KEY is not set.",
                ),
                AgentStep(
                    thought="Other thought.",
                    tool="noop",
                    tool_input={},
                    observation="Unmatched observation.",
                ),
            ],
        )

        localized = localize_report(report, "zh-CN")

        self.assertIn("检测到主要源码语言：Python (2)。", localized.overview)
        self.assertIn("扫描样本中未检测到应用源码文件。", localized.overview)
        self.assertIn("Custom sentence.", localized.overview)
        self.assertEqual(localized.findings[0].title, "补充包含安装和使用说明的 README")
        self.assertEqual(localized.findings[0].category, "文档")
        self.assertIn("发现 2 个源码文件", localized.findings[0].evidence[0])
        self.assertIn("README.md 缺少", localized.findings[0].evidence[2])
        self.assertIn("匹配到疑似密钥模式", localized.findings[0].evidence[6])
        self.assertEqual(localized.findings[1].title, "Unknown title")
        self.assertIsNotNone(localized.ai_review)
        self.assertEqual(localized.ai_review.error, "OPENAI_API_KEY 未设置。")
        self.assertIn("扫描了 4 个文件", localized.agent_trace[0].observation)
        self.assertIn("已检查 README.md", localized.agent_trace[1].observation)
        self.assertIn("已使用 ollama/llama3.2", localized.agent_trace[3].observation)
        self.assertIn("AI Review 生成失败", localized.agent_trace[6].observation)
        self.assertEqual(localized.agent_trace[7].observation, "Unmatched observation.")

    def test_localize_report_returns_english_report_unchanged_and_handles_no_ai(self) -> None:
        report = ReviewReport(
            repo_name="example",
            generated_at="2026-05-28T00:00:00+00:00",
            overview=[],
            metrics={},
            framework_signals={},
            findings=[],
            ai_review=None,
            agent_trace=None,
        )

        self.assertIs(localize_report(report, "en"), report)
        localized = localize_report(report, "zh-CN")
        self.assertIsNone(localized.ai_review)
        self.assertIsNone(localized.agent_trace)


if __name__ == "__main__":
    unittest.main()
