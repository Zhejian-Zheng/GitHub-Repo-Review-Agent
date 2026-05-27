from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import unittest

from repo_review_agent.function_agent import (
    OpenAIFunctionCallingAgent,
    extract_function_calls,
    is_safe_relative_path,
)


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

    def test_safe_relative_path_rejects_escape(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")

            self.assertTrue(is_safe_relative_path(root, "README.md"))
            self.assertFalse(is_safe_relative_path(root, "../README.md"))
            self.assertFalse(is_safe_relative_path(root, "/tmp/README.md"))

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
                "output_text": "## AI Architecture Summary\nA small repository review agent.",
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
        self.assertIn("AI Architecture Summary", report.ai_review.summary)
        self.assertEqual(mock_post_json.call_count, 5)


if __name__ == "__main__":
    unittest.main()
