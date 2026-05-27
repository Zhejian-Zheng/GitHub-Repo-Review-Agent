from unittest.mock import patch
import unittest

from repo_review_agent.llm import add_ai_review, build_review_prompt, extract_openai_text
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


if __name__ == "__main__":
    unittest.main()
