import unittest
from unittest.mock import patch

from repo_review_agent.llm import (
    AIProviderError,
    attach_ai_error,
    build_review_prompt,
    coerce_plain_text_review,
    extract_json_object,
    extract_markdown_review_sections,
    normalize_ai_review_summary,
    parse_ai_review_sections,
    render_ai_review_sections,
    resolve_model,
)
from repo_review_agent.models import Finding, ReviewReport


def sample_report() -> ReviewReport:
    return ReviewReport(
        repo_name="example",
        generated_at="2026-05-27T00:00:00+00:00",
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
        framework_signals={"Pytest": ["pyproject.toml: pytest"]},
        findings=[
            Finding(
                title="Add automated tests for the core behavior",
                severity="medium",
                category="testing",
                evidence=["2 source file(s) found, but no tests were detected."],
                recommendation="Add small tests around the scanner and analyzer.",
                evidence_paths=["src/app.py"],
            )
        ],
    )


def sample_ai_review_json() -> str:
    return """
{
  "architecture_summary": [
    "This repository is a small review agent with a scanner, analyzer, and report renderer."
  ],
  "risks": [
    "The scan is evidence-bound but still shallow, so dependency and runtime behavior need deeper checks."
  ],
  "project_highlights": [
    "The project combines deterministic findings with optional AI synthesis and traceable agent steps."
  ],
  "next_steps": [
    "Add golden report fixtures so output quality can be regression tested."
  ]
}
"""


class LLMTests(unittest.TestCase):
    def test_build_review_prompt_contains_structured_report(self) -> None:
        prompt = build_review_prompt(sample_report())

        self.assertIn("AI Architecture Summary", prompt)
        self.assertIn('"repo_name": "example"', prompt)
        self.assertIn("Do not invent files", prompt)
        self.assertIn("Return only a valid JSON object", prompt)
        self.assertIn("architecture_summary", prompt)
        self.assertIn("project_highlights", prompt)
        self.assertIn('"evidence_paths": [', prompt)
        self.assertIn('"src/app.py"', prompt)
        self.assertIn("Prompt tuning guidance", prompt)
        self.assertIn("Few-shot examples", prompt)
        self.assertIn("risky-js-app", prompt)

    def test_build_review_prompt_wraps_untrusted_repository_data(self) -> None:
        prompt = build_review_prompt(sample_report())

        self.assertIn("untrusted data", prompt)
        self.assertIn("BEGIN UNTRUSTED REPOSITORY DATA", prompt)
        self.assertIn("END UNTRUSTED REPOSITORY DATA", prompt)
        self.assertIn("prompt-injection risk", prompt)
        # The data boundary must enclose the JSON payload.
        begin = prompt.index("BEGIN UNTRUSTED REPOSITORY DATA")
        end = prompt.index("END UNTRUSTED REPOSITORY DATA")
        self.assertLess(begin, prompt.index('"repo_name"'))
        self.assertLess(prompt.index('"repo_name"'), end)

    def test_build_review_prompt_supports_chinese(self) -> None:
        prompt = build_review_prompt(sample_report(), language="zh-CN")

        self.assertIn("Simplified Chinese", prompt)
        self.assertIn("## AI 架构总结", prompt)
        self.assertIn("## 项目亮点", prompt)
        self.assertNotIn("## 简历亮点", prompt)
        self.assertIn("project_highlights should", prompt)
        self.assertIn("prioritized recommendations", prompt)
        self.assertIn("Do not add any resume", prompt)
        self.assertIn("Each value must be an array", prompt)
        self.assertIn("确定性扫描", prompt)
        self.assertIn("risky-js-app", prompt)

    def test_resolve_model_supports_openrouter_default(self) -> None:
        self.assertEqual(resolve_model("openrouter", None), "openrouter/auto")

    def test_resolve_model_supports_anthropic_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_model("anthropic", None), "claude-opus-4-8")

    @patch.dict("os.environ", {"OPENAI_MODEL": "env-openai", "OLLAMA_MODEL": "env-ollama"})
    def test_resolve_model_uses_environment_and_unknown_fallback(self) -> None:
        self.assertEqual(resolve_model("openai", None), "env-openai")
        self.assertEqual(resolve_model("ollama", None), "env-ollama")
        self.assertEqual(resolve_model("custom", None), "unknown")
        self.assertEqual(resolve_model("custom", "explicit"), "explicit")

    def test_normalize_ai_review_summary_renames_resume_pitch(self) -> None:
        summary = "## AI Architecture Summary\nLooks good.\n\n## Resume Pitch\n- Old title."

        normalized = normalize_ai_review_summary(summary, language="en")

        self.assertIn("## Project Highlights", normalized)
        self.assertNotIn("Resume Pitch", normalized)

    def test_normalize_ai_review_summary_renames_chinese_resume_highlights(self) -> None:
        summary = "## AI 架构总结\n不错。\n\n## 简历亮点\n- 旧标题。"

        normalized = normalize_ai_review_summary(summary, language="zh-CN")

        self.assertIn("## 项目亮点", normalized)
        self.assertNotIn("简历亮点", normalized)

    def test_normalize_ai_review_summary_renames_bare_chinese_resume_heading(self) -> None:
        summary = "AI 架构总结\n不错。\n\n简历亮点\n*\n*\n* 多语言开发经验。"

        normalized = normalize_ai_review_summary(summary, language="zh-CN")

        self.assertIn("## 项目亮点", normalized)
        self.assertNotIn("简历亮点", normalized)

    def test_parse_ai_review_sections_accepts_fenced_json(self) -> None:
        sections = parse_ai_review_sections(
            f"```json\n{sample_ai_review_json()}\n```",
            language="en",
        )

        self.assertEqual(
            sections["project_highlights"],
            [
                "The project combines deterministic findings with optional AI synthesis and traceable agent steps."
            ],
        )

    def test_parse_ai_review_sections_accepts_markdown_fallback(self) -> None:
        sections = parse_ai_review_sections(
            """
## AI 架构总结
这是一个前后端结合的仓库评审工具。

## 主要风险
- 线上配置仍依赖正确的环境变量。

## 项目亮点
- 已覆盖认证、历史记录和异步任务。

## 推荐下一步
- 增加端到端截图和部署检查。
""",
            language="zh-CN",
        )

        self.assertEqual(sections["architecture_summary"], ["这是一个前后端结合的仓库评审工具。"])
        self.assertEqual(sections["risks"], ["线上配置仍依赖正确的环境变量。"])
        self.assertEqual(sections["project_highlights"], ["已覆盖认证、历史记录和异步任务。"])
        self.assertEqual(sections["next_steps"], ["增加端到端截图和部署检查。"])

    def test_parse_ai_review_sections_accepts_plain_text_fallback(self) -> None:
        sections = parse_ai_review_sections(
            "This repository has a scanner, analyzer, FastAPI backend, and React UI."
        )

        self.assertEqual(
            sections["architecture_summary"],
            ["This repository has a scanner, analyzer, FastAPI backend, and React UI."],
        )
        self.assertEqual(sections["risks"], [])

    def test_coerce_plain_text_review_ignores_empty_text(self) -> None:
        sections = coerce_plain_text_review("\n\n")

        self.assertFalse(any(sections.values()))

    def test_parse_ai_review_sections_can_disable_text_fallback(self) -> None:
        with self.assertRaises(AIProviderError):
            parse_ai_review_sections("not json", allow_text_fallback=False)

    def test_extract_markdown_review_sections_ignores_unknown_text(self) -> None:
        sections = extract_markdown_review_sections(
            """
Intro text the model should not have returned.

### Architecture Summary
Scanner, analyzer, API, and web UI are separated clearly.

### Top Risks
1. Public deployment still depends on configured secrets.
"""
        )

        self.assertEqual(
            sections["architecture_summary"],
            ["Scanner, analyzer, API, and web UI are separated clearly."],
        )
        self.assertEqual(
            sections["risks"], ["Public deployment still depends on configured secrets."]
        )
        self.assertEqual(sections["project_highlights"], [])

    def test_parse_ai_review_sections_coerces_aliases_strings_and_nested_items(self) -> None:
        sections = parse_ai_review_sections(
            """
{
  "summary": "- Built from scanner signals",
  "top_risks": {"items": ["1. Runtime checks are still shallow"]},
  "highlights": [{"title": "Traceable agent", "impact": "Easy to audit"}],
  "recommendations": 123
}
""",
            language="en",
        )

        self.assertEqual(sections["architecture_summary"], ["Built from scanner signals"])
        self.assertEqual(sections["risks"], ["Runtime checks are still shallow"])
        self.assertEqual(
            sections["project_highlights"], ["Traceable agent - impact: Easy to audit"]
        )
        self.assertEqual(sections["next_steps"], ["123"])

    def test_parse_ai_review_sections_rejects_invalid_or_empty_json(self) -> None:
        with self.assertRaises(AIProviderError):
            parse_ai_review_sections("[]")

        with self.assertRaises(AIProviderError):
            parse_ai_review_sections("{}")

    def test_extract_json_object_recovers_embedded_object(self) -> None:
        self.assertEqual(extract_json_object('prefix {"ok": true} suffix'), {"ok": True})
        self.assertIsNone(extract_json_object("no object here"))

    def test_render_ai_review_sections_uses_fixed_chinese_markdown(self) -> None:
        sections = parse_ai_review_sections(sample_ai_review_json(), language="zh-CN")

        markdown = render_ai_review_sections(sections, language="zh-CN")

        self.assertIn("## AI 架构总结", markdown)
        self.assertIn("## 项目亮点", markdown)
        self.assertNotIn("简历亮点", markdown)
        self.assertNotIn("\n- \n", markdown)

    def test_render_ai_review_sections_fills_empty_sections(self) -> None:
        markdown = render_ai_review_sections({"architecture_summary": ["Only summary."]})

        self.assertIn("Only summary.", markdown)
        self.assertIn("No risk details were returned", markdown)
        self.assertIn("The model did not return project highlights.", markdown)

    def test_attach_ai_error_records_resolved_model(self) -> None:
        report = attach_ai_error(
            sample_report(),
            provider="openai",
            model=None,
            error="broken",
        )

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.status, "error")
        self.assertEqual(report.ai_review.model, "gpt-5-mini")


if __name__ == "__main__":
    unittest.main()
