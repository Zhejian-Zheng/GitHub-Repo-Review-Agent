from unittest.mock import patch
import unittest

from repo_review_agent.llm import (
    add_ai_review,
    build_review_prompt,
    extract_openai_text,
    extract_openrouter_text,
    parse_ai_review_sections,
    render_ai_review_sections,
    normalize_ai_review_summary,
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

    def test_extract_openai_text_handles_output_text(self) -> None:
        text = extract_openai_text({"output_text": "hello"})

        self.assertEqual(text, "hello")

    def test_extract_openai_text_handles_output_content(self) -> None:
        text = extract_openai_text(
            {
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "hello"},
                            {"type": "output_text", "text": "world"},
                        ]
                    }
                ]
            }
        )

        self.assertEqual(text, "hello\nworld")

    def test_extract_openrouter_text_handles_chat_completion(self) -> None:
        text = extract_openrouter_text(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "hello from openrouter",
                        }
                    }
                ]
            }
        )

        self.assertEqual(text, "hello from openrouter")

    def test_resolve_model_supports_openrouter_default(self) -> None:
        self.assertEqual(resolve_model("openrouter", None), "openrouter/auto")

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
            ["The project combines deterministic findings with optional AI synthesis and traceable agent steps."],
        )

    def test_render_ai_review_sections_uses_fixed_chinese_markdown(self) -> None:
        sections = parse_ai_review_sections(sample_ai_review_json(), language="zh-CN")

        markdown = render_ai_review_sections(sections, language="zh-CN")

        self.assertIn("## AI 架构总结", markdown)
        self.assertIn("## 项目亮点", markdown)
        self.assertNotIn("简历亮点", markdown)
        self.assertNotIn("\n- \n", markdown)

    @patch("repo_review_agent.llm.generate_with_ollama")
    def test_add_ai_review_attaches_provider_output(self, mock_generate) -> None:
        mock_generate.return_value = sample_ai_review_json()

        report = add_ai_review(
            sample_report(),
            provider="ollama",
            model="llama3.2",
            timeout=1,
        )

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.provider, "ollama")
        self.assertEqual(report.ai_review.status, "generated")
        self.assertIsNotNone(report.ai_review.sections)
        self.assertIn("## AI Architecture Summary", report.ai_review.summary)
        self.assertIn("## Project Highlights", report.ai_review.summary)

    @patch("repo_review_agent.llm.generate_with_openrouter")
    def test_add_ai_review_supports_openrouter(self, mock_generate) -> None:
        mock_generate.return_value = sample_ai_review_json()

        report = add_ai_review(
            sample_report(),
            provider="openrouter",
            model="openrouter/auto",
            timeout=1,
        )

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.provider, "openrouter")
        self.assertEqual(report.ai_review.model, "openrouter/auto")
        self.assertEqual(
            report.ai_review.sections["next_steps"],
            ["Add golden report fixtures so output quality can be regression tested."],
        )


if __name__ == "__main__":
    unittest.main()
