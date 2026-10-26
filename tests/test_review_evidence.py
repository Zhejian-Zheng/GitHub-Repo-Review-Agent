import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.agent import RepoReviewAgent
from repo_review_agent.review_tools import ReviewSession


class ReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'app.py').write_text('def hello():\n    return "hello"\n')
        (self.root / 'README.md').write_text('# Example\nInstall with pip.\n')
        self.session = ReviewSession(self.root)
        self.tools = {tool.name: tool for tool in self.session.tools()}

    def test_source_discovery_search_and_line_read(self):
        self.assertTrue({'list_files', 'search_code', 'read_file_lines'} <= self.tools.keys())
        files = json.loads(self.tools['list_files'].invoke({'pattern': 'src/*.py'}))
        self.assertEqual(files['paths'], ['src/app.py'])
        matches = json.loads(self.tools['search_code'].invoke({'query': 'return'}))
        self.assertEqual(matches['matches'][0]['path'], 'src/app.py')
        self.assertEqual(matches['matches'][0]['line'], 2)
        result = json.loads(self.tools['read_file_lines'].invoke({'path': 'src/app.py', 'start_line': 2, 'end_line': 2}))
        self.assertEqual(result['lines'], [{'line': 2, 'text': '    return "hello"'}])

    def test_secret_redacted_from_tool_and_exported_trace(self):
        secret = 'ghp_' + 'A' * 36
        (self.root / 'README.md').write_text('# Example\nTOKEN=' + secret + '\npassword="fake-private-password"\n')
        output = self.tools['inspect_file'].invoke({'path': 'README.md'})
        self.assertNotIn(secret, output)
        self.assertNotIn('fake-private-password', output)
        report = RepoReviewAgent().run(self.root)
        exported = json.dumps(report.to_dict())
        self.assertNotIn(secret, exported)
        self.assertNotIn('fake-private-password', exported)
        self.assertNotIn('# Example', report.agent_trace[1].observation)

    def test_sensitive_aliases_not_readable_or_searchable(self):
        (self.root / 'private.pem').write_text('secret material')
        (self.root / 'alias.md').symlink_to(self.root / 'private.pem')
        result = self.tools['inspect_file'].invoke({'path': 'alias.md'})
        self.assertIn('error', result)
        self.assertNotIn('secret material', result)

    def test_partial_secret_read_does_not_leak_prefix(self):
        secret = 'ghp_' + 'A' * 36
        (self.root / 'README.md').write_text(secret)
        output = self.tools['inspect_file'].invoke({'path': 'README.md', 'max_chars': 12})
        self.assertNotIn('ghp_', output)

    def test_agent_preserves_verified_finding_and_rejects_unread_evidence(self):
        from unittest.mock import patch

        from fake_model import SECTIONS, ScriptedModel, call, final

        finding = {'title': 'Example finding', 'severity': 'low', 'path': 'src/app.py',
                   'start_line': 2, 'end_line': 2, 'evidence': '    return "hello"',
                   'confidence': 0.9, 'recommendation': 'Review this return.'}
        for read in (False, True):
            with self.subTest(read=read):
                responses = [final({**SECTIONS, 'findings': [finding]})]
                if read:
                    responses.insert(0, call('read_file_lines', {'path': 'src/app.py', 'start_line': 2, 'end_line': 2}))
                model = ScriptedModel(responses=responses)
                with patch('repo_review_agent.agent.create_chat_model', return_value=model):
                    report = RepoReviewAgent(ai_provider='ollama', max_turns=3).run(self.root)
                self.assertEqual(report.ai_review.status, 'generated' if read else 'error')
                if read:
                    self.assertEqual(report.ai_review.findings[0]['path'], 'src/app.py')
                    from repo_review_agent.report import render_markdown
                    self.assertIn('src/app.py:2', render_markdown(report))

    def test_progress_marks_actual_analysis_and_model_stages(self):
        from unittest.mock import patch

        from fake_model import ScriptedModel, final

        from repo_review_agent.service import run_review

        for mode in ('direct', 'agent', 'function-calling', 'chatgpt-agent'):
            phases = []
            model = ScriptedModel(responses=[final()])
            with patch('repo_review_agent.agent.create_chat_model', return_value=model):
                run_review(self.root, mode=mode, on_progress=phases.append)
            self.assertEqual(phases, ['analyzing', 'ai'] if mode in ('function-calling', 'chatgpt-agent') else ['analyzing'])

    def test_secrets_masked_in_prompts_and_report_exports(self):
        from dataclasses import replace

        from repo_review_agent.llm import build_review_prompt
        from repo_review_agent.report import render_markdown

        secret = 'sk-' + 'z' * 30
        report = replace(RepoReviewAgent().run(self.root), overview=['api_key="' + secret + '"'])
        self.assertNotIn(secret, build_review_prompt(report))
        self.assertNotIn(secret, json.dumps(report.to_dict()))
        self.assertNotIn(secret, render_markdown(report))

    def test_line_reads_reject_invalid_ranges_and_binary_content(self):
        (self.root / 'binary.py').write_bytes(b'abc\x00def')
        read = self.tools['read_file_lines']
        for args in ({'path': 'binary.py'}, {'path': 'src/app.py', 'start_line': 5, 'end_line': 2},
                     {'path': 'src/app.py', 'start_line': 1, 'end_line': 101}):
            self.assertIn('error', json.loads(read.invoke(args)))

    def test_search_cannot_expose_secrets_and_paginates(self):
        secret = 'github_pat_' + 'x' * 40
        (self.root / 'src' / 'config.py').write_text('TOKEN=' + secret)
        matches = json.loads(self.tools['search_code'].invoke({'query': secret}))
        self.assertEqual(matches['matches'], [])
        page = json.loads(self.tools['list_files'].invoke({'limit': 1}))
        self.assertEqual(len(page['paths']), 1)
        self.assertEqual(page['next_offset'], 1)

    def test_bad_evidence_locations_and_changed_quotes_rejected(self):
        from repo_review_agent.review_schema import EvidenceFinding

        base = dict(title='Finding', severity='low', path='src/app.py', start_line=1,
                    end_line=1, evidence='def hello():', confidence=1, recommendation='Review')
        self.tools['read_file_lines'].invoke({'path': 'src/app.py', 'start_line': 1, 'end_line': 2})
        self.assertEqual(len(self.session.validate_findings([EvidenceFinding(**base)])), 1)
        for changes in ({'end_line': 1000}, {'start_line': 2, 'end_line': 1},
                        {'evidence': 'made up'}, {'path': '../outside.py'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.session.validate_findings([EvidenceFinding(**{**base, **changes})])
        (self.root / 'src' / 'app.py').write_text('changed')
        with self.assertRaises(ValueError):
            self.session.validate_findings([EvidenceFinding(**base)])

    def test_search_pagination_does_not_skip_remaining_matches_in_file(self):
        (self.root / 'src' / 'app.py').write_text('match one\nmatch two\n')
        first = json.loads(self.tools['search_code'].invoke({'query': 'match', 'pattern': 'src/app.py', 'limit': 1}))
        self.assertIsNotNone(first['next_offset'])
        second = json.loads(self.tools['search_code'].invoke({'query': 'match', 'pattern': 'src/app.py', 'limit': 1,
                              'offset': first['next_offset'], 'start_line': first['next_line']}))
        self.assertEqual(second['matches'][0]['line'], 2)

    def test_search_does_not_destroy_full_line_evidence(self):
        from repo_review_agent.review_schema import EvidenceFinding

        line = 'return "' + 'x' * 400 + '"'
        (self.root / 'src' / 'app.py').write_text(line)
        self.tools['read_file_lines'].invoke({'path': 'src/app.py', 'end_line': 1})
        self.tools['search_code'].invoke({'query': 'return'})
        finding = EvidenceFinding(title='Finding', severity='low', path='src/app.py', start_line=1,
                                  end_line=1, evidence=line, confidence=0.8, recommendation='Review')
        self.assertEqual(len(self.session.validate_findings([finding])), 1)

    def test_oversize_first_line_reports_truncation_and_search_skips_sensitive_files(self):
        (self.root / 'src' / 'app.py').write_text('x' * 9000)
        (self.root / 'private.pem').write_text('search-me')
        result = json.loads(self.tools['read_file_lines'].invoke({'path': 'src/app.py'}))
        self.assertEqual(result['lines'], [])
        self.assertTrue(result['truncated'])
        result = json.loads(self.tools['search_code'].invoke({'query': 'search-me'}))
        self.assertEqual(result['matches'], [])
