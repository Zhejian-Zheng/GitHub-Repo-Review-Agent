import json
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from repo_review_agent import questions
from repo_review_agent.provider import AIProviderError

REPORT = {'repo_name':'example','overview':['Python app'], 'findings':[{
    'title':'Unsafe return', 'severity':'low', 'source':'ai', 'path':'app.py',
    'start_line':2,'end_line':2,'evidence':['    return token'],
    'evidence_paths':['app.py'],'recommendation':'Review the return.'
}]}


class QuestionTests(unittest.TestCase):
    def test_offline_followup_returns_existing_evidence(self):
        result = questions.answer_report_question(REPORT, 'What is unsafe in the return?')
        self.assertIn('Unsafe return', result['answer'])
        self.assertEqual(result['citations'][0]['path'], 'app.py')
        self.assertEqual(result['citations'][0]['start_line'], 2)
        self.assertTrue(result['limitations'])

    def test_model_cannot_invent_citation_ids(self):
        model = FakeListChatModel(responses=[json.dumps({'answer':'Invented','citation_ids':[100]})])
        with patch('repo_review_agent.questions.create_chat_model', return_value=model), self.assertRaises(AIProviderError):
            questions.answer_report_question(REPORT, 'Explain this', provider='ollama')

    def test_model_answer_cites_only_existing_report_evidence_and_redacts(self):
        secret = 'sk-' + 'a' * 30
        model = FakeListChatModel(responses=[json.dumps({'answer':'Use '+secret,'citation_ids':[0]})])
        with patch('repo_review_agent.questions.create_chat_model', return_value=model):
            result = questions.answer_report_question(REPORT, 'Explain', provider='ollama', token_budget=10000)
        self.assertNotIn(secret, result['answer'])
        self.assertEqual(result['citations'][0]['evidence'], '    return token')
        self.assertEqual(result['usage']['model_calls'], 1)

    def test_outside_paths_and_oversized_requests_rejected(self):
        report = {**REPORT, 'findings':[{**REPORT['findings'][0], 'path':'../secret', 'evidence_paths':['../secret']}]}
        result = questions.answer_report_question(report, 'why')
        self.assertEqual(result['citations'], [])
        for query in ('', 'x' * 2001):
            with self.assertRaises(ValueError):
                questions.answer_report_question(REPORT, query)
        with self.assertRaises(ValueError):
            questions.answer_report_question({'overview':['x'*200001]}, 'why')

    def test_malformed_report_containers_raise_validation_errors(self):
        for report in [None, [], {'findings': None}, {'findings': 5},
                       {'findings': 'text'}, {'ai_review': 'text'},
                       {'ai_review': {'findings': None}}]:
            with self.subTest(report=report), self.assertRaises(ValueError):
                questions.answer_report_question(report, 'Why?')

    def test_malformed_individual_evidence_is_skipped_without_crashing(self):
        malformed = [None, 5, {'evidence_paths': 42}, {'evidence_paths': {'wrong': 'path'}},
                     {'path': 5}, {'path': 'app.py', 'evidence': None},
                     {'path': '/absolute.py', 'evidence': ['text']},
                     {'path': 'folder\\secret.py', 'evidence': ['text']}]
        result = questions.answer_report_question({'findings': malformed}, 'Why?')
        self.assertEqual(result['citations'], [])

    def test_duplicate_and_redacted_evidence_are_not_cited(self):
        finding = REPORT['findings'][0]
        secret = {**finding, 'evidence': ['sk-' + 'a' * 30]}
        report = {**REPORT, 'findings': [finding, finding, secret], 'ai_review': {'findings': [finding]}}
        self.assertEqual(len(questions.answer_report_question(report, 'Why?')['citations']), 1)

    def test_invalid_lines_are_omitted_and_chinese_insufficient_answer_is_localized(self):
        finding = {**REPORT['findings'][0], 'start_line': True, 'end_line': True}
        citation = questions.answer_report_question({'findings': [finding]}, 'Why?')['citations'][0]
        self.assertIsNone(citation['start_line'])
        result = questions.answer_report_question({'findings': []}, '为什么？', language='zh-CN')
        self.assertIn('没有足够', result['answer'])
        self.assertIn('未重新读取仓库', result['limitations'][0])

    def test_provider_citations_required_when_evidence_exists_and_deduplicated(self):
        for ids, should_fail in [([], True), ([-1], True), ([0, 0], False)]:
            model = FakeListChatModel(responses=[json.dumps({'answer': 'Supported', 'citation_ids': ids})])
            with self.subTest(ids=ids), patch('repo_review_agent.questions.create_chat_model', return_value=model):
                if should_fail:
                    with self.assertRaises(AIProviderError):
                        questions.answer_report_question(REPORT, 'Why?', provider='ollama')
                else:
                    self.assertEqual(len(questions.answer_report_question(REPORT, 'Why?', provider='ollama')['citations']), 1)

    def test_provider_answer_with_no_evidence_is_explicitly_uncited(self):
        model = FakeListChatModel(responses=['{"answer":"Insufficient evidence","citation_ids":[]}'])
        with patch('repo_review_agent.questions.create_chat_model', return_value=model):
            result = questions.answer_report_question({'findings': []}, 'Why?', provider='ollama')
        self.assertEqual(result['citations'], [])
