import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from repo_review_agent import budget
from repo_review_agent.agent import RepoReviewAgent


class BudgetTests(unittest.TestCase):
    def test_reservation_blocks_call_before_exhaustion(self):
        ledger = budget.TokenBudget(300, output_limit=100)
        ledger.reserve([HumanMessage(content='small')])
        with self.assertRaisesRegex(budget.BudgetExceeded, 'budget'):
            ledger.reserve([HumanMessage(content='x' * 1000)])
        self.assertEqual(ledger.calls, 1)

    def test_usage_missing_is_unknown_not_zero(self):
        ledger = budget.TokenBudget(1000, output_limit=100)
        ledger.reserve([HumanMessage(content='hi')])
        ledger.record([AIMessage(content='ok')])
        self.assertIsNone(ledger.summary()['actual_tokens'])
        self.assertGreater(ledger.summary()['reserved_tokens'], 0)

    def test_usage_accumulates_and_output_cap_validated(self):
        ledger = budget.TokenBudget(1000, output_limit=100)
        for _ in range(2):
            ledger.reserve([HumanMessage(content='hi')])
            ledger.record([AIMessage(content='ok', usage_metadata={'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12})])
        self.assertEqual(ledger.summary()['actual_tokens'], 24)
        with self.assertRaises(ValueError):
            budget.TokenBudget(0, output_limit=1)

    def test_agent_budget_blocks_model_but_preserves_baseline(self):
        from fake_model import ScriptedModel, final
        model = ScriptedModel(responses=[final()])
        with TemporaryDirectory() as tmp, patch('repo_review_agent.agent.create_chat_model', return_value=model):
            report = RepoReviewAgent(ai_provider='ollama', ai_token_budget=256).run(Path(tmp))
        self.assertEqual(report.ai_review.status, 'error')
        self.assertIn('budget', report.ai_review.error.lower())
        self.assertEqual(model.seen_messages, [])
        self.assertTrue(report.findings)

    def test_agent_budget_records_model_calls(self):
        from fake_model import ScriptedModel, final
        model = ScriptedModel(responses=[final()])
        with TemporaryDirectory() as tmp, patch('repo_review_agent.agent.create_chat_model', return_value=model):
            report = RepoReviewAgent(ai_provider='ollama', ai_token_budget=50000).run(Path(tmp))
        self.assertEqual(report.ai_review.status, 'generated')
        self.assertEqual(report.metrics['ai_usage']['model_calls'], 1)
        self.assertIsNone(report.metrics['ai_usage']['actual_tokens'])

    def test_direct_repair_consumes_one_shared_budget(self):
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from test_llm import sample_report

        from repo_review_agent.llm import add_ai_review
        model = FakeListChatModel(responses=['invalid'])
        with patch('repo_review_agent.llm.create_chat_model', return_value=model), self.assertRaisesRegex(budget.BudgetExceeded, 'budget'):
            add_ai_review(sample_report(), provider='ollama', token_budget=13000)

    def test_failed_request_does_not_report_unknown_usage_as_zero(self):
        ledger=budget.TokenBudget(1000,output_limit=100)
        ledger.reserve([HumanMessage(content='hi')])
        self.assertIsNone(ledger.summary()['actual_tokens'])
