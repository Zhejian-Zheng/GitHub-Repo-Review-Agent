"""Opt-in provider smoke test; never spends API credits in the default suite.

REPO_REVIEW_LIVE_TEST=1 REPO_REVIEW_LIVE_PROVIDER=ollama python -m unittest discover -s tests -p test_live_provider.py
Supply provider credentials/model through the usual environment variables.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.agent import RepoReviewAgent


@unittest.skipUnless(os.environ.get('REPO_REVIEW_LIVE_TEST') == '1', 'opt-in real provider test')
class LiveProviderTests(unittest.TestCase):
    def test_live_model_completes_structured_review(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('# Tiny example\nUsage: python app.py\n')
            (root / 'app.py').write_text('print("hello")\n')
            report = RepoReviewAgent(
                ai_provider=os.environ.get('REPO_REVIEW_LIVE_PROVIDER', 'ollama'),
                ai_model=os.environ.get('REPO_REVIEW_LIVE_MODEL'),
                ai_timeout=30, max_turns=4, max_tool_calls=8,
                ai_max_output_tokens=2000, fail_on_ai_error=True,
            ).run(root)
            self.assertEqual(report.ai_review.status, 'generated')
            self.assertTrue(all(report.ai_review.sections.values()))
            self.assertTrue(report.agent_trace)
