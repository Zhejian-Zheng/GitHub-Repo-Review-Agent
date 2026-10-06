import json
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_llm import sample_report

from repo_review_agent.auth import AuthUser
from repo_review_agent.cli import main
from repo_review_agent.findings import review_findings
from repo_review_agent.history import HistorySaveResult, RunComparison
from repo_review_agent.models import Finding
from repo_review_agent.web import ReviewRequest, execute_review_request


class ExportFeedbackTests(unittest.TestCase):
    def test_web_response_keeps_feedback_after_history_save(self):
        report = replace(sample_report(), findings=[Finding('Example','high','code',['evidence'],'Fix',['app.py'])])
        fingerprint = review_findings(report)[0].fingerprint
        feedback = [{'fingerprint':fingerprint,'status':'false_positive'}]
        result = HistorySaveResult('repo','run',100,RunComparison([],[],[]),feedback)
        with TemporaryDirectory() as tmp, patch('repo_review_agent.web.run_review_for_path',return_value=report), patch(
            'repo_review_agent.web.SupabaseHistoryStore.from_env'
        ) as store:
            store.return_value.save_report.return_value=result
            response = execute_review_request(ReviewRequest(target=tmp,save_history=True),AuthUser('owner'))
        self.assertEqual(response['report']['finding_feedback'],feedback)
        self.assertNotIn('[HIGH] Example',response['markdown'])

    def test_cli_json_keeps_feedback_after_history_save(self):
        report = replace(sample_report(), findings=[Finding('Example','high','code',['evidence'],'Fix',['app.py'])])
        feedback = [{'fingerprint':review_findings(report)[0].fingerprint,'status':'ignored'}]
        result = HistorySaveResult('repo','run',100,RunComparison([],[],[]),feedback)
        with TemporaryDirectory() as tmp, patch('repo_review_agent.cli.run_review',return_value=report), patch(
            'repo_review_agent.cli.SupabaseHistoryStore.from_env'
        ) as store, redirect_stdout(StringIO()):
            store.return_value.save_report.return_value=result
            output = Path(tmp)/'out.json'
            self.assertEqual(main([tmp,'--save-history','--json',str(output)]),0)
            data = json.loads(output.read_text())
        self.assertEqual(data['finding_feedback'],feedback)
