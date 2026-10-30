"""Regressions for report identity, bounded model context and evidence attribution."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.analyzer import analyze_repository
from repo_review_agent.findings import effective_findings, finding_fingerprint
from repo_review_agent.linters import _finding_for_code
from repo_review_agent.llm import build_review_prompt
from repo_review_agent.models import Finding, ReviewReport
from repo_review_agent.pr_bot import build_pr_review_diff
from repo_review_agent.questions import answer_report_question


def ruff_group(count=1, path='app.py'):
    return _finding_for_code('F821', [
        {'filename': path, 'location': {'row': i + 1, 'column': 1},
         'message': f'Undefined name missing_{i}'} for i in range(count)
    ], Path('.'))


def report_with(findings):
    return ReviewReport('example', '', [], {'review_coverage': {
        'version': 1, 'rules_complete': True, 'ruff_complete': True,
        'inventory_complete': True, 'inventory_paths': ['app.py', 'other.py'],
    }}, {}, findings)


class ReviewFollowupTests(unittest.TestCase):
    def test_ruff_count_and_sample_changes_preserve_identity_and_feedback(self):
        before = report_with([ruff_group()])
        identity = finding_fingerprint(before.findings[0])
        for count, path in ((2, 'app.py'), (1, 'other.py'), (7, 'other.py')):
            after = report_with([ruff_group(count, path)])
            diff = build_pr_review_diff(after, before)
            self.assertEqual(diff.new_findings, [])
            self.assertEqual(diff.resolved_findings, [])
            self.assertEqual(len(diff.existing_findings), 1)
            self.assertEqual(effective_findings(replace(after, finding_feedback=[
                {'fingerprint': identity, 'status': 'ignored'}])), [])

    def test_legacy_ruff_identity_is_not_falsely_resolved_or_feedback_reassigned(self):
        legacy = replace(ruff_group(), rule_id=None, fingerprint='legacy-saved-id')
        before = report_with([legacy])
        after = report_with([ruff_group(2, 'other.py')])
        # Even disappearance of a sampled path cannot establish group resolution.
        after.metrics['review_coverage']['inventory_paths'] = ['other.py']
        diff = build_pr_review_diff(after, before)
        self.assertEqual(diff.resolved_findings, [])
        self.assertEqual(len(diff.unverified_findings), 1)
        self.assertEqual(len(effective_findings(replace(after, finding_feedback=[
            {'fingerprint': 'legacy-saved-id', 'status': 'ignored'}]))), 1)
        self.assertEqual(len(build_pr_review_diff(report_with([]), before).resolved_findings), 1)

    def test_ruff_requires_complete_scan_to_resolve(self):
        before = report_with([ruff_group()])
        clean = report_with([])
        self.assertEqual(len(build_pr_review_diff(clean, before).resolved_findings), 1)
        clean.metrics['review_coverage']['ruff_complete'] = False
        self.assertEqual(build_pr_review_diff(clean, before).resolved_findings, [])

    def test_prompt_budget_preserves_valid_json_and_important_findings(self):
        report = report_with([Finding('Important defect', 'high', 'security',
                                     ['unsafe code\n' * 5000], 'Fix this', ['app.py'])])
        report.metrics['top_level_items'] = [f'component_{i}_' + 'long_' * 30 for i in range(500)]
        report.metrics['changed_files'] = [{'filename': 'x' * 1000, 'patch': 'y' * 10000}] * 100
        report.metrics['review_scope'] = 'incremental'
        report = replace(report, overview=['overview' * 5000] * 30,
                         framework_signals={'Python': ['path' * 5000] * 50},
                         findings=[Finding('Low priority', 'low', 'style', ['x'], 'Fix')] * 45 + report.findings)
        for evidence_mode in (False, True):
            prompt = build_review_prompt(report, include_evidence=evidence_mode)
            data = prompt.split('----- BEGIN UNTRUSTED REPOSITORY DATA -----\n```json\n', 1)[1].split('\n```', 1)[0]
            parsed = json.loads(data)
            self.assertLessEqual(len(data), 24000)
            self.assertEqual(parsed['findings'][0]['title'], 'Important defect')
            self.assertEqual(parsed['review_scope'], 'incremental')
            self.assertTrue(parsed['truncated_fields'])

    def test_multifile_dependency_evidence_keeps_correct_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text('{"dependencies":{"beta":"*"}}')
            (root / 'requirements.txt').write_text('alpha\n')
            report = analyze_repository(root).to_dict()
        result = answer_report_question(report, 'Why is alpha in requirements.txt unconstrained?')
        citation = result['citations'][0]
        self.assertEqual(citation['path'], 'requirements.txt')
        self.assertNotIn('package.json:', citation['evidence'])
        self.assertIn('alpha is unconstrained', citation['evidence'])

    def test_small_incremental_context_preserves_changed_line_ranges(self):
        report = report_with([])
        changes = [{'filename': 'app.py', 'status': 'modified', 'added_line_ranges': [[3, 5]]}]
        report.metrics.update(review_scope='incremental', changed_files=changes)
        prompt = build_review_prompt(report)
        data = prompt.split('----- BEGIN UNTRUSTED REPOSITORY DATA -----\n```json\n', 1)[1].split('\n```', 1)[0]
        self.assertEqual(json.loads(data)['changed_files'], changes)

    def test_ambiguous_multifile_evidence_preserves_all_sources_without_line_numbers(self):
        finding = {'title': 'Coupled modules', 'evidence_paths': ['a.py', 'b.py'],
                   'evidence': ['These two modules depend on one another.'],
                   'recommendation': 'Separate dependencies.', 'start_line': 1, 'end_line': 2}
        result = answer_report_question({'findings': [finding]}, 'Why?')
        citation = result['citations'][0]
        self.assertIsNone(citation['path'])
        self.assertEqual(citation['paths'], ['a.py', 'b.py'])
        self.assertIsNone(citation['start_line'])
