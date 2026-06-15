import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.function_agent import (
    FunctionCall,
    FunctionCallingState,
    OpenAIFunctionCallingAgent,
    compact_preview,
    extract_function_calls,
    is_safe_relative_path,
    recommend_files_to_inspect,
)
from repo_review_agent.scanner import scan_repository


class OpenAIFunctionCallingAgentTests(unittest.TestCase):
    def test_extract_function_calls(self) -> None:
        calls = extract_function_calls(
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "inspect_file",
                        "arguments": '{"path":"README.md","max_chars":4000}',
                    }
                ]
            }
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "inspect_file")
        self.assertEqual(calls[0].arguments["path"], "README.md")

    def test_extract_function_calls_ignores_non_calls_and_bad_json_arguments(self) -> None:
        calls = extract_function_calls(
            {
                "output": [
                    {"type": "message", "content": "done"},
                    {
                        "type": "function_call",
                        "call_id": "call_bad",
                        "name": "scan_repository",
                        "arguments": "{bad json",
                    },
                ]
            }
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].arguments, {})

    def test_safe_relative_path_rejects_escape(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            self.assertTrue(is_safe_relative_path(root, "README.md"))
            self.assertFalse(is_safe_relative_path(root, "../README.md"))
            self.assertFalse(is_safe_relative_path(root, "/tmp/README.md"))
            self.assertFalse(is_safe_relative_path(root, "missing.md"))
            self.assertFalse(is_safe_relative_path(root, ""))

    def test_recommend_files_to_inspect_deduplicates_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
            (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
            snapshot = scan_repository(root)

        self.assertEqual(
            recommend_files_to_inspect(snapshot),
            ["README.md", "pyproject.toml", ".github/workflows/ci.yml"],
        )

    def test_compact_preview_truncates_long_content(self) -> None:
        preview = compact_preview("a" * 20, max_chars=10)

        self.assertEqual(preview, "aaaaaaa...")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("repo_review_agent.function_agent._post_json")
    def test_function_calling_agent_runs_model_driven_tool_loop(self, mock_post_json) -> None:
        mock_post_json.side_effect = [
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_scan",
                        "name": "scan_repository",
                        "arguments": "{}",
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_inspect",
                        "name": "inspect_file",
                        "arguments": '{"path":"README.md","max_chars":4000}',
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_analyze",
                        "name": "analyze_repository",
                        "arguments": "{}",
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_report",
                        "name": "generate_report",
                        "arguments": '{"format":"markdown"}',
                    }
                ]
            },
            {
                "output_text": """
{
  "architecture_summary": [
    "A small repository review agent with scanning, analysis, and report rendering."
  ],
  "risks": [
    "The review depends on static signals, so runtime behavior still needs manual validation."
  ],
  "project_highlights": [
    "The agent exposes a traceable tool loop and structured report output."
  ],
  "next_steps": [
    "Add fixture-based golden report tests for representative repositories."
  ]
}
""",
                "output": [],
            },
        ]

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            report = OpenAIFunctionCallingAgent(model="gpt-test").run(root)

        self.assertIsNotNone(report.agent_trace)
        self.assertEqual(
            [step.tool for step in report.agent_trace or []],
            ["scan_repository", "inspect_file", "analyze_repository", "generate_report"],
        )
        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.provider, "openai-functions")
        self.assertEqual(report.ai_review.status, "generated")
        self.assertIsNotNone(report.ai_review.sections)
        self.assertIn("AI Architecture Summary", report.ai_review.summary)
        self.assertIn("Project Highlights", report.ai_review.summary)
        self.assertEqual(mock_post_json.call_count, 5)

    @patch.dict(os.environ, {}, clear=True)
    def test_function_calling_agent_requires_openai_key(self) -> None:
        with TemporaryDirectory() as tmp, self.assertRaises(Exception) as context:
            OpenAIFunctionCallingAgent().run(Path(tmp))

        self.assertIn("OPENAI_API_KEY is not set", str(context.exception))

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("repo_review_agent.function_agent._post_json")
    def test_function_calling_agent_requires_report(self, mock_post_json) -> None:
        mock_post_json.return_value = {"output_text": "{}", "output": []}

        with TemporaryDirectory() as tmp, self.assertRaises(Exception) as context:
            OpenAIFunctionCallingAgent(max_turns=1).run(Path(tmp))

        self.assertIn("stopped before producing a report", str(context.exception))

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("repo_review_agent.function_agent._post_json")
    def test_function_calling_agent_records_invalid_final_json_as_ai_error(self, mock_post_json) -> None:
        mock_post_json.side_effect = [
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_scan",
                        "name": "scan_repository",
                        "arguments": "{}",
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_analyze",
                        "name": "analyze_repository",
                        "arguments": "{}",
                    },
                ]
            },
            {"output_text": "not json", "output": []},
        ]

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            report = OpenAIFunctionCallingAgent(model="gpt-test").run(root)

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.status, "error")
        self.assertIn("not valid JSON", report.ai_review.error)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("repo_review_agent.function_agent._post_json")
    def test_function_calling_agent_records_missing_final_text_as_ai_error(self, mock_post_json) -> None:
        mock_post_json.side_effect = [
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_analyze",
                        "name": "analyze_repository",
                        "arguments": "{}",
                    }
                ]
            },
            {"output": []},
        ]

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            report = OpenAIFunctionCallingAgent(model="gpt-test").run(root)

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.status, "error")
        self.assertEqual(report.ai_review.error, "Model did not return a final text response.")

    def test_execute_tool_handles_unknown_and_invalid_report_format(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            agent = OpenAIFunctionCallingAgent(model="gpt-test")
            state = FunctionCallingState(root=root)

            unknown = agent._execute_tool(state, FunctionCall("1", "missing", {}))
            invalid_format = agent._execute_tool(
                state,
                FunctionCall("2", "generate_report", {"format": "json"}),
            )
            unsafe_inspect = agent._execute_tool(
                state,
                FunctionCall("3", "inspect_file", {"path": "../secret", "max_chars": 10}),
            )

        self.assertFalse(unknown["ok"])
        self.assertFalse(invalid_format["ok"])
        self.assertFalse(unsafe_inspect["ok"])

    def test_generate_report_runs_analysis_when_needed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            agent = OpenAIFunctionCallingAgent(model="gpt-test")
            state = FunctionCallingState(root=root)

            result = agent._generate_report(state, {"format": "markdown"})

        self.assertTrue(result["ok"])
        self.assertIsNotNone(state.report)
        self.assertIsNotNone(state.rendered_report)


if __name__ == "__main__":
    unittest.main()
