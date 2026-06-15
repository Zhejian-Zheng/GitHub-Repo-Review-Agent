import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from repo_review_agent.llm import (
    AIProviderError,
    add_ai_review,
    attach_ai_error,
    build_review_prompt,
    extract_json_object,
    extract_openai_text,
    extract_openrouter_text,
    generate_with_ollama,
    generate_with_openai,
    generate_with_openrouter,
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

    def test_extract_openrouter_text_handles_content_parts(self) -> None:
        text = extract_openrouter_text(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "hello"},
                                {"type": "text", "text": "world"},
                            ]
                        }
                    },
                    "ignored",
                ]
            }
        )

        self.assertEqual(text, "hello\nworld")

    def test_extract_openai_text_ignores_non_dict_content(self) -> None:
        text = extract_openai_text({"output": ["ignored", {"content": ["nope", {"text": "ok"}]}]})

        self.assertEqual(text, "ok")

    def test_resolve_model_supports_openrouter_default(self) -> None:
        self.assertEqual(resolve_model("openrouter", None), "openrouter/auto")

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
            ["The project combines deterministic findings with optional AI synthesis and traceable agent steps."],
        )

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
        self.assertEqual(sections["project_highlights"], ["Traceable agent - impact: Easy to audit"])
        self.assertEqual(sections["next_steps"], ["123"])

    def test_parse_ai_review_sections_rejects_invalid_or_empty_json(self) -> None:
        with self.assertRaises(AIProviderError):
            parse_ai_review_sections("not json")

        with self.assertRaises(AIProviderError):
            parse_ai_review_sections("[]")

        with self.assertRaises(AIProviderError):
            parse_ai_review_sections("{}")

    def test_extract_json_object_recovers_embedded_object(self) -> None:
        self.assertEqual(extract_json_object("prefix {\"ok\": true} suffix"), {"ok": True})
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

    def test_add_ai_review_rejects_unknown_provider(self) -> None:
        with self.assertRaises(AIProviderError):
            add_ai_review(sample_report(), provider="unknown")

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

    def test_generate_with_openai_requires_key_and_text(self) -> None:
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(AIProviderError):
            generate_with_openai("prompt", model="gpt-test", timeout=1, max_output_tokens=10)

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "key"}, clear=True),
            patch("repo_review_agent.llm._post_json", return_value={"output": []}),
            self.assertRaises(AIProviderError),
        ):
            generate_with_openai("prompt", model="gpt-test", timeout=1, max_output_tokens=10)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "key"}, clear=True)
    @patch("repo_review_agent.llm._post_json")
    def test_generate_with_openai_returns_text(self, mock_post_json) -> None:
        mock_post_json.return_value = {"output_text": "ok"}

        text = generate_with_openai("prompt", model="gpt-test", timeout=1, max_output_tokens=10)

        self.assertEqual(text, "ok")

    def test_generate_with_openrouter_requires_key_and_handles_error_payload(self) -> None:
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(AIProviderError):
            generate_with_openrouter("prompt", model="model", timeout=1, max_output_tokens=10)

        with (
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "key"}, clear=True),
            patch("repo_review_agent.llm._post_json", return_value={"error": {"message": "bad"}}),
            self.assertRaises(AIProviderError),
        ):
            generate_with_openrouter("prompt", model="model", timeout=1, max_output_tokens=10)

        with (
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "key"}, clear=True),
            patch("repo_review_agent.llm._post_json", return_value={"choices": []}),
            self.assertRaises(AIProviderError),
        ):
            generate_with_openrouter("prompt", model="model", timeout=1, max_output_tokens=10)

    def test_generate_with_ollama_requires_response_text(self) -> None:
        with (
            patch("repo_review_agent.llm._post_json", return_value={"response": ""}),
            self.assertRaises(AIProviderError),
        ):
            generate_with_ollama(
                "prompt",
                model="llama",
                timeout=1,
                max_output_tokens=10,
                base_url="http://localhost:11434/",
            )

        with (
            patch("repo_review_agent.llm._post_json", return_value={"response": 123}),
            self.assertRaises(AIProviderError),
        ):
            generate_with_ollama(
                "prompt",
                model="llama",
                timeout=1,
                max_output_tokens=10,
                base_url="http://localhost:11434/",
            )

    @patch("repo_review_agent.llm._post_json")
    def test_generate_with_ollama_returns_response_text(self, mock_post_json) -> None:
        mock_post_json.return_value = {"response": "local review"}

        text = generate_with_ollama(
            "prompt",
            model="llama",
            timeout=1,
            max_output_tokens=10,
            base_url="http://localhost:11434/",
        )

        self.assertEqual(text, "local review")
        self.assertEqual(mock_post_json.call_args.args[0], "http://localhost:11434/api/generate")

    @patch.dict(
        "os.environ",
        {
            "OPENROUTER_API_KEY": "key",
            "OPENROUTER_HTTP_REFERER": "https://example.com",
            "OPENROUTER_APP_TITLE": "Demo",
        },
        clear=True,
    )
    @patch("repo_review_agent.llm._post_json")
    def test_generate_with_openrouter_sends_optional_headers(self, mock_post_json) -> None:
        mock_post_json.return_value = {"choices": [{"message": {"content": "ok"}}]}

        text = generate_with_openrouter("prompt", model="model", timeout=1, max_output_tokens=10)

        self.assertEqual(text, "ok")
        headers = mock_post_json.call_args.kwargs["headers"]
        self.assertEqual(headers["HTTP-Referer"], "https://example.com")
        self.assertEqual(headers["X-OpenRouter-Title"], "Demo")

    @patch("repo_review_agent.llm.urlopen")
    def test_post_json_handles_http_url_json_and_shape_errors(self, mock_urlopen) -> None:
        from repo_review_agent.llm import _post_json

        http_error = HTTPError(
            "https://api.example.test",
            500,
            "server error",
            {},
            BytesIO(b"broken"),
        )
        mock_urlopen.side_effect = http_error
        with self.assertRaises(AIProviderError):
            _post_json("https://api.example.test", {}, timeout=1, headers={})

        mock_urlopen.side_effect = URLError("offline")
        with self.assertRaises(AIProviderError):
            _post_json("https://api.example.test", {}, timeout=1, headers={})

        bad_response = MagicMock()
        bad_response.__enter__.return_value.read.return_value = b"not-json"
        mock_urlopen.side_effect = None
        mock_urlopen.return_value = bad_response
        with self.assertRaises(AIProviderError):
            _post_json("https://api.example.test", {}, timeout=1, headers={})

        list_response = MagicMock()
        list_response.__enter__.return_value.read.return_value = b"[]"
        mock_urlopen.return_value = list_response
        with self.assertRaises(AIProviderError):
            _post_json("https://api.example.test", {}, timeout=1, headers={})


if __name__ == "__main__":
    unittest.main()
