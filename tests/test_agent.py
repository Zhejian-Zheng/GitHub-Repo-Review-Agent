import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fake_model import ScriptedModel, call, final
from langchain_core.messages import AIMessage

from repo_review_agent.agent import RepoReviewAgent
from repo_review_agent.llm import AIProviderError
from repo_review_agent.report import render_markdown


class RepoReviewAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "README.md").write_text("# Example\nEvidence from README.")
        (self.root / "app.py").write_text('print("hello")')

    def test_offline_graph_and_trace(self):
        report = RepoReviewAgent().run(self.root)
        self.assertEqual(report.metrics["agent_framework"], "langchain")
        tools = [step.tool for step in report.agent_trace]
        self.assertEqual(tools[0], "scan_repository")
        self.assertIn("inspect_file", tools)
        self.assertIn("analyze_repository", tools)
        self.assertEqual(tools[-1], "finalize_report")
        self.assertIn("README.md", report.metrics["agent_inspected_files"])
        self.assertIn("## Agent Trace", render_markdown(report))
        self.assertIsNone(report.ai_review)

    def test_real_agent_calls_tools_and_returns_structured_review(self):
        model = ScriptedModel(responses=[call("inspect_file", {"path": "app.py"}), final()])
        with patch("repo_review_agent.agent.create_chat_model", return_value=model):
            report = RepoReviewAgent(ai_provider="ollama", report_language="zh-CN").run(self.root)
        self.assertEqual(report.ai_review.status, "generated")
        self.assertEqual(report.ai_review.sections["risks"], ["Evidence-bound risk."])
        self.assertIn("app.py", report.metrics["agent_inspected_files"])
        self.assertIn("## AI 架构总结", report.ai_review.summary)
        self.assertTrue(
            any("print" in m.content for m in model.seen_messages[-1] if m.type == "tool")
        )
        self.assertIn("Simplified Chinese", str(model.seen_messages[0]))

    def test_invalid_tool_arguments_are_recoverable(self):
        model = ScriptedModel(
            responses=[call("inspect_file", {"path": "README.md", "max_chars": -1}), final()]
        )
        with patch("repo_review_agent.agent.create_chat_model", return_value=model):
            report = RepoReviewAgent(ai_provider="ollama").run(self.root)
        self.assertEqual(report.ai_review.status, "generated")
        self.assertTrue(
            any(m.type == "tool" and m.status == "error" for m in model.seen_messages[-1])
        )

    def test_structured_output_is_repaired(self):
        model = ScriptedModel(responses=[final({"risks": []}), final()])
        with patch("repo_review_agent.agent.create_chat_model", return_value=model):
            report = RepoReviewAgent(ai_provider="ollama").run(self.root)
        self.assertEqual(report.ai_review.status, "generated")
        self.assertEqual(len(model.seen_messages), 2)

    def test_provider_failure_preserves_base_report_or_raises(self):
        with patch(
            "repo_review_agent.agent.create_chat_model", side_effect=AIProviderError("offline")
        ):
            report = RepoReviewAgent(ai_provider="ollama").run(self.root)
            self.assertTrue(report.findings)
            self.assertEqual(report.ai_review.status, "error")
            self.assertIn("offline", report.ai_review.error)
            with self.assertRaises(AIProviderError):
                RepoReviewAgent(ai_provider="ollama", fail_on_ai_error=True).run(self.root)

    def test_missing_final_output_is_error(self):
        model = ScriptedModel(responses=[AIMessage(content="done")])
        with patch("repo_review_agent.agent.create_chat_model", return_value=model):
            report = RepoReviewAgent(ai_provider="ollama", max_turns=2).run(self.root)
        self.assertEqual(report.ai_review.status, "error")

    def test_model_loop_and_tool_batch_are_bounded(self):
        for response in (
            call("scan_repository"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "scan_repository", "args": {}, "id": str(i)} for i in range(10)
                ],
            ),
        ):
            model = ScriptedModel(responses=[response])
            with patch("repo_review_agent.agent.create_chat_model", return_value=model):
                report = RepoReviewAgent(ai_provider="ollama", max_turns=2, max_tool_calls=3).run(
                    self.root
                )
            self.assertEqual(report.ai_review.status, "error")
            self.assertLessEqual(len(model.seen_messages), 2)

    def test_offline_budget_does_not_return_incomplete_success(self):
        with self.assertRaises(RuntimeError):
            RepoReviewAgent(max_steps=1).run(self.root)

    def test_runs_do_not_share_state(self):
        agent = RepoReviewAgent()
        with TemporaryDirectory() as other:
            root2 = Path(other)
            (root2 / "package.json").write_text("{}")
            with ThreadPoolExecutor(max_workers=2) as pool:
                reports = list(pool.map(agent.run, [self.root, root2]))
            self.assertIn("README.md", reports[0].metrics["agent_inspected_files"])
            self.assertNotIn("README.md", reports[1].metrics["agent_inspected_files"])
            self.assertNotIn("package.json", reports[0].metrics["agent_inspected_files"])

    def test_empty_repository(self):
        with TemporaryDirectory() as tmp:
            report = RepoReviewAgent().run(Path(tmp))
        self.assertEqual(report.metrics["agent_inspected_files"], [])
