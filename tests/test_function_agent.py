import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fake_model import ScriptedModel, final

from repo_review_agent.function_agent import OpenAIFunctionCallingAgent
from repo_review_agent.llm import AIProviderError


class FunctionCallingAgentTests(unittest.TestCase):
    def test_legacy_agent_uses_langchain_and_preserves_label(self):
        with (
            TemporaryDirectory() as tmp,
            patch(
                "repo_review_agent.agent.create_chat_model",
                return_value=ScriptedModel(responses=[final()]),
            ),
        ):
            report = OpenAIFunctionCallingAgent(model="test").run(Path(tmp))
        self.assertEqual(report.ai_review.provider, "openai-functions")
        self.assertEqual(report.ai_review.status, "generated")
        self.assertEqual(report.metrics["agent_framework"], "langchain")

    def test_legacy_mode_requires_api_key(self):
        with (
            TemporaryDirectory() as tmp,
            patch.dict("os.environ", {}, clear=True),
            self.assertRaisesRegex(AIProviderError, "OPENAI_API_KEY"),
        ):
            OpenAIFunctionCallingAgent().run(Path(tmp))
