import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent import evaluation
from repo_review_agent.models import Finding, ReviewReport


def report():
    return ReviewReport('example', '', [], {}, {}, [Finding('Expected', 'low', 'testing', ['evidence'], 'fix')])


class EvaluationTests(unittest.TestCase):
    def test_incomplete_labels_do_not_claim_precision(self):
        scores = evaluation.score_report(report(), {'expected_findings': ['Expected'], 'forbidden_findings': ['Wrong']})
        self.assertEqual(scores['recall'], 1)
        self.assertEqual(scores['forbidden_pass'], 1)
        self.assertIsNone(scores['precision'])

    def test_exhaustive_labels_detect_false_positive_and_missing_findings(self):
        scores = evaluation.score_report(report(), {'expected_findings': ['Missing'], 'acceptable_findings': ['Missing'], 'forbidden_findings': ['Expected']})
        self.assertEqual(scores['recall'], 0)
        self.assertEqual(scores['precision'], 0)
        self.assertEqual(scores['forbidden_pass'], 0)

    def test_dataset_runs_and_failing_threshold_exits_nonzero(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'repo').mkdir()
            dataset = root / 'dataset.json'
            dataset.write_text(json.dumps({'cases': [{'id': 'one', 'target': 'repo', 'expected_findings': ['Missing']}]}))
            with patch('repo_review_agent.evaluation.run_review', return_value=report()):
                result = evaluation.run_dataset(dataset)
                self.assertEqual(result['summary']['recall'], 0)
                self.assertEqual(result['cases'][0]['id'], 'one')
                self.assertIsNone(result['cases'][0]['actual_tokens'])
                output = root / 'out.json'
                code = evaluation.main([str(dataset), '--output', str(output), '--min-recall', '1'])
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output.read_text())['summary']['recall'], 0)

    def test_dataset_rejects_unbounded_or_outside_targets(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / 'dataset.json'
            for target in ('../outside', 'https://github.com/example/repo'):
                dataset.write_text(json.dumps({'cases': [{'id':'one','target': target,'expected_findings': []}]}))
                with self.assertRaises(ValueError):
                    evaluation.run_dataset(dataset)

    def test_sdk_scores_only_export_known_numeric_metrics(self):
        from repo_review_agent import telemetry
        calls = []
        class Client:
            def get_current_trace_id(self):
                return 'trace-123'
            def create_score(self, **kwargs):
                calls.append(kwargs)
        with patch.object(telemetry, '_STATE', telemetry._State(Client(), object)):
            self.assertTrue(telemetry.record_evaluation_scores({'recall': 1, 'precision': None, 'secret': 3}))
        self.assertEqual(calls, [{'trace_id':'trace-123','name':'recall','value':1.0,'data_type':'NUMERIC'}])

    def test_citations_require_existing_exact_safe_source_lines(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text('first\nsecond\n')
            valid = {'title': 'AI', 'source': 'ai', 'path': 'app.py', 'start_line': 1,
                     'end_line': 2, 'evidence': ['first', 'second']}
            invalid = [{**valid, 'path': '../outside'}, {**valid, 'path': 'absent.py'},
                       {**valid, 'start_line': 0}, {**valid, 'end_line': 3},
                       {**valid, 'evidence': ['wrong']}, {**valid, 'path': None},
                       {**valid, 'start_line': None}, {**valid, 'start_line': True, 'end_line': True,
                                                     'evidence': ['first']}]
            for finding in invalid:
                with self.subTest(finding=finding):
                    fake = SimpleNamespace(to_dict=lambda finding=finding: {'findings': [valid, finding]}, ai_review=None)
                    scores = evaluation.score_report(fake, {}, root)
                    self.assertEqual(scores['citation_validity'], .5)
                    self.assertIsNone(scores['precision'])
            fake = SimpleNamespace(to_dict=lambda: {'findings': [valid]}, ai_review=None)
            self.assertIsNone(evaluation.score_report(fake, {})['citation_validity'])

    def test_empty_findings_exhaustive_labels_and_ai_failure_scores(self):
        from repo_review_agent.models import AIReview
        empty = ReviewReport('repo', '', [], {}, {}, [],
                             ai_review=AIReview('ollama', 'test', 'failed', '', error='Offline'))
        scores = evaluation.score_report(empty, {'acceptable_findings': [], 'expected_findings': []})
        self.assertEqual(scores['precision'], 1)
        self.assertEqual(scores['ai_success'], 0)
        self.assertIsNone(scores['citation_validity'])

    def test_dataset_validates_duplicate_ids_repeats_and_size_before_review(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'repo').mkdir()
            dataset = root / 'dataset.json'
            case = {'id': 'one', 'target': 'repo'}
            with patch.object(evaluation, 'run_review') as review:
                for repeats in [0, 6]:
                    with self.assertRaises(ValueError):
                        evaluation.run_dataset(dataset, repeats=repeats)
                for content in [json.dumps({'cases': [case, case]}), ' ' * 1000001,
                                json.dumps({'cases': []}), json.dumps({'cases': [case] * 51})]:
                    dataset.write_text(content)
                    with self.assertRaises(ValueError):
                        evaluation.run_dataset(dataset)
                review.assert_not_called()

    def test_dataset_repeats_isolate_fixtures_and_preserve_usage(self):
        from dataclasses import replace
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / 'repo'
            fixture.mkdir()
            (fixture / 'app.py').write_text('original')
            dataset = root / 'dataset.json'
            dataset.write_text(json.dumps({'cases': [{'id': 'one', 'target': 'repo'}]}))
            def review(copied, **kwargs):
                self.assertEqual((copied / 'app.py').read_text(), 'original')
                (copied / 'app.py').write_text('mutated')
                self.assertEqual(kwargs['ai_token_budget'], 1234)
                return replace(report(), metrics={'ai_usage': {'actual_tokens': 123}})
            with patch.object(evaluation, 'run_review', side_effect=review), patch.object(
                    evaluation, 'record_evaluation_scores', return_value=False):
                result = evaluation.run_dataset(dataset, repeats=2, token_budget=1234)
            self.assertEqual([row['trial'] for row in result['cases']], [1, 2])
            self.assertEqual(result['cases'][0]['actual_tokens'], 123)
            self.assertFalse(result['cases'][0]['langfuse_scores_queued'])
            self.assertEqual((fixture / 'app.py').read_text(), 'original')

    def test_cli_precision_provider_failure_and_invalid_threshold_gates(self):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        good = {'recall': 1, 'precision': 1, 'forbidden_pass': 1, 'ai_success': 1}
        for changed, options, expected in [({}, [], 0), ({'precision': None}, ['--min-precision', '.5'], 1),
                                          ({'precision': .4}, ['--min-precision', '.5'], 1),
                                          ({'ai_success': 0}, ['--provider', 'ollama'], 1),
                                          ({'forbidden_pass': 0}, [], 1)]:
            with self.subTest(changed=changed), patch.object(evaluation, 'run_dataset',
                    return_value={'summary': {**good, **changed}}), redirect_stdout(StringIO()):
                self.assertEqual(evaluation.main(['dataset.json', *options]), expected)
        for options in [['--min-recall', '1.1'], ['--min-precision', '-.1']]:
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                evaluation.main(['dataset.json', *options])
            self.assertEqual(error.exception.code, 2)
