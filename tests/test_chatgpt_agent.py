import unittest
from pathlib import Path
from unittest.mock import patch

from repo_review_agent.chatgpt_agent import CHATGPT_API_PROVIDER, ChatGPTReviewAgent
from repo_review_agent.models import AIReview, ReviewReport


def sample_report(ai_review: AIReview | None = None) -> ReviewReport:
    return ReviewReport(
        repo_name="example",
        generated_at="2026-05-28T00:00:00+00:00",
        overview=[],
        metrics={},
        framework_signals={},
        findings=[],
        ai_review=ai_review,
    )


class ChatGPTReviewAgentTests(unittest.TestCase):
    @patch("repo_review_agent.chatgpt_agent.OpenAIFunctionCallingAgent")
    def test_run_labels_ai_review_provider_as_chatgpt_api(self, mock_agent_class) -> None:
        mock_agent_class.return_value.run.return_value = sample_report(
            AIReview(
                provider="openai-functions",
                model="gpt-test",
                status="generated",
                summary="ok",
            )
        )

        report = ChatGPTReviewAgent(model="gpt-test").run(Path("."))

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.provider, CHATGPT_API_PROVIDER)
        mock_agent_class.assert_called_once()
        mock_agent_class.return_value.run.assert_called_once_with(Path("."))

    @patch("repo_review_agent.chatgpt_agent.OpenAIFunctionCallingAgent")
    def test_run_preserves_report_without_ai_review(self, mock_agent_class) -> None:
        expected = sample_report(ai_review=None)
        mock_agent_class.return_value.run.return_value = expected

        report = ChatGPTReviewAgent().run(Path("."))

        self.assertIs(report, expected)


if __name__ == "__main__":
    unittest.main()
