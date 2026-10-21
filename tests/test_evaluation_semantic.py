"""Regression tests for evidence matching and human semantic adjudication."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from repo_review_agent import evaluation


def candidate(path='app.py', start=2, end=2, evidence=None, title='A plausible but unproven defect'):
    return {'title': title, 'source': 'ai', 'path': path, 'start_line': start,
            'end_line': end, 'evidence': evidence or ['return count / total']}


def labels():
    return {'expected_defects': ['zero-division'], 'acceptable_defects': [
        {'id': 'zero-division', 'description': 'total can be zero; division raises ZeroDivisionError',
         'locations': [{'path': 'app.py', 'start_line': 2, 'end_line': 2}]}]}


def fake_report(findings):
    return SimpleNamespace(to_dict=lambda: {'findings': findings}, ai_review=None)


class LocationScoringTests(unittest.TestCase):
    def test_exact_quote_and_location_never_prove_semantic_correctness(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text('def ratio(count, total):\nreturn count / total\n')
            scores = evaluation.score_report(fake_report([candidate()]), labels(), root)
        self.assertEqual(scores['evidence_location_recall'], 1)
        self.assertEqual(scores['evidence_location_precision'], 1)
        self.assertIsNone(scores['semantic_precision'])
        self.assertIsNone(scores['semantic_recall'])

    def test_duplicates_wrong_files_and_fabricated_quotes_do_not_inflate_matches(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text('def ratio(count, total):\nreturn count / total\n')
            (root / 'other.py').write_text('def ratio(count, total):\nreturn count / total\n')
            findings = [candidate(), candidate(), candidate(path='other.py'), candidate(evidence=['fake'])]
            scores = evaluation.score_report(fake_report(findings), labels(), root)
        self.assertEqual(scores['evidence_location_recall'], 1)
        self.assertEqual(scores['evidence_location_precision'], .25)

    def test_broad_citations_cannot_match_a_narrow_defect_location(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text('def ratio(count, total):\nreturn count / total\n')
            scores = evaluation.score_report(fake_report([candidate(start=1, evidence=[
                'def ratio(count, total):', 'return count / total'])]), labels(), root)
        self.assertEqual(scores['citation_validity'], 1)
        self.assertEqual(scores['evidence_location_recall'], 0)
        self.assertEqual(scores['evidence_location_precision'], 0)

    def test_clean_cases_penalize_any_ai_finding_but_ignore_hygiene_findings(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = {'expected_defects': [], 'acceptable_defects': []}
            scores = evaluation.score_report(fake_report([candidate()]), clean, root)
            self.assertEqual(scores['evidence_location_precision'], 0)
            self.assertEqual(scores['evidence_location_recall'], 1)
            scores = evaluation.score_report(fake_report([{'title': 'License', 'source': 'static'}]), clean, root)
            self.assertEqual(scores['evidence_location_precision'], 1)

    def test_required_defects_take_priority_over_optional_overlapping_locations(self):
        data = labels()
        data['acceptable_defects'].insert(0, {**data['acceptable_defects'][0], 'id': 'optional'})
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text('def ratio(count, total):\nreturn count / total\n')
            scores = evaluation.score_report(fake_report([candidate()]), data, root)
        self.assertEqual(scores['evidence_location_recall'], 1)
        self.assertEqual(scores['evidence_location_precision'], 1)

    def test_missing_source_keeps_location_metrics_unknown(self):
        scores = evaluation.score_report(fake_report([candidate()]), labels())
        self.assertIsNone(scores['evidence_location_recall'])
        self.assertIsNone(scores['evidence_location_precision'])

    def test_location_threshold_rejects_missing_and_insufficient_scores(self):
        from contextlib import redirect_stdout
        from io import StringIO
        good = {'recall': 1, 'precision': 1, 'forbidden_pass': 1, 'ai_success': 1}
        for value, expected in [(None, 1), (.49, 1), (.5, 0)]:
            with patch.object(evaluation, 'run_dataset', return_value={'summary': {
                **good, 'evidence_location_recall': value, 'evidence_location_precision': value}}), redirect_stdout(StringIO()):
                self.assertEqual(evaluation.main(['dataset.json', '--min-location-recall', '.5',
                                                  '--min-location-precision', '.5']), expected)

    def test_semantic_dataset_rejects_invalid_labels_before_running_reviews(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'repo').mkdir()
            path = root / 'dataset.json'
            invalid = [
                {**labels(), 'expected_defects': ['unknown']},
                {**labels(), 'acceptable_defects': labels()['acceptable_defects'] * 2},
                {**labels(), 'acceptable_defects': [{**labels()['acceptable_defects'][0],
                    'locations': [{'path': '../escape.py', 'start_line': 1, 'end_line': 2}]}]},
            ]
            for data in invalid:
                path.write_text(json.dumps({'cases': [{'id': 'test', 'target': 'repo', **data}]}))
                with self.assertRaises(ValueError):
                    evaluation.run_dataset(path)
