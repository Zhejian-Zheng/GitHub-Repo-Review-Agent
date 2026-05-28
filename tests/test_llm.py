from unittest.mock import patch
import unittest

from repo_review_agent.llm import (
    add_ai_review,
    build_review_prompt,
    extract_openai_text,
    extract_openrouter_text,
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
            )
        ],
    )


class LLMTests(unittest.TestCase):
    def test_build_review_prompt_contains_structured_report(self) -> None:
        prompt = build_review_prompt(sample_report())

        self.assertIn("AI Architecture Summary", prompt)
        self.assertIn('"repo_name": "example"', prompt)
        self.assertIn("Do not invent files", prompt)

    def test_build_review_prompt_supports_chinese(self) -> None:
        prompt = build_review_prompt(sample_report(), language="zh-CN")

        self.assertIn("Simplified Chinese", prompt)
        self.assertIn("## AI 架构总结", prompt)
        self.assertIn("## 简历亮点", prompt)

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

    @patch("repo_review_agent.llm.generate_with_ollama")
    def test_add_ai_review_attaches_provider_output(self, mock_generate) -> None:
        mock_generate.return_value = "## AI Architecture Summary\nLooks good."

        report = add_ai_review(
            sample_report(),
            provider="ollama",
            model="llama3.2",
            timeout=1,
        )

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.provider, "ollama")
        self.assertEqual(report.ai_review.status, "generated")
        self.assertIn("Looks good", report.ai_review.summary)

    @patch("repo_review_agent.llm.generate_with_openrouter")
    def test_add_ai_review_supports_openrouter(self, mock_generate) -> None:
        mock_generate.return_value = "## AI Architecture Summary\nOpenRouter works."

        report = add_ai_review(
            sample_report(),
            provider="openrouter",
            model="openrouter/auto",
            timeout=1,
        )

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.provider, "openrouter")
        self.assertEqual(report.ai_review.model, "openrouter/auto")
        self.assertIn("OpenRouter works", report.ai_review.summary)


if __name__ == "__main__":
    unittest.main()
