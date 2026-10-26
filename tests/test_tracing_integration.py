import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from test_llm import sample_ai_review_json, sample_report

from repo_review_agent.agent import RepoReviewAgent
from repo_review_agent.llm import add_ai_review


class Events(BaseCallbackHandler):
    def __init__(self):
        self.models = 0
        self.tools = 0

    def on_chat_model_start(self, *args, **kwargs):
        self.models += 1

    def on_tool_start(self, *args, **kwargs):
        self.tools += 1


class TracingIntegrationTests(unittest.TestCase):
    def test_agent_callbacks_include_model_and_tool_events(self):
        from fake_model import ScriptedModel, call, final

        events = Events()
        closed = []

        @contextmanager
        def tracing():
            yield {"callbacks": [events]}
            closed.append(True)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('# Example')
            model = ScriptedModel(responses=[call('list_files', {}), final()])
            with patch('repo_review_agent.agent.review_tracing', tracing), patch(
                'repo_review_agent.agent.create_chat_model', return_value=model
            ):
                report = RepoReviewAgent(ai_provider='ollama').run(root)
        self.assertEqual(report.ai_review.status, 'generated')
        self.assertEqual(events.models, 2)
        self.assertGreaterEqual(events.tools, 1)
        self.assertEqual(closed, [True])

    def test_direct_repair_uses_same_trace_and_flushes_once(self):
        events = Events()
        closed = []

        @contextmanager
        def tracing():
            yield {"callbacks": [events]}
            closed.append(True)

        model = FakeListChatModel(responses=['invalid', sample_ai_review_json()])
        with patch('repo_review_agent.llm.review_tracing', tracing), patch(
            'repo_review_agent.llm.create_chat_model', return_value=model
        ):
            report = add_ai_review(sample_report(), provider='ollama')
        self.assertEqual(report.ai_review.status, 'generated')
        self.assertEqual(events.models, 2)
        self.assertEqual(closed, [True])
