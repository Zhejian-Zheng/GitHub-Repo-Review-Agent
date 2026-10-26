import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.config import ReviewConfig, apply_review_config, load_review_config
from repo_review_agent.models import AIReview, Finding, ReviewReport
from repo_review_agent.scanner import scan_repository


class ConfigTests(unittest.TestCase):
    def test_suppression_count_survives_repeat_policy_and_later_ai_findings(self):
        report = ReviewReport('repo', '', [], {}, {}, [
            Finding('Suppressed rule', 'high', 'security', [], '', rule_id='security.example'),
            Finding('Kept rule', 'low', 'testing', [], ''),
        ])
        config = ReviewConfig(disabled_rules=['security.example'], disabled_categories=['code'])
        first = apply_review_config(report, config)
        self.assertEqual(first.metrics['config_suppressed_findings'], 1)
        repeated = apply_review_config(first, config)
        self.assertEqual(repeated.metrics['config_suppressed_findings'], 1)
        with_ai = replace(repeated, ai_review=AIReview('fake', 'fake', 'generated', '',
            findings=[{'title': 'AI defect', 'severity': 'high', 'path': 'app.py'}]))
        final = apply_review_config(with_ai, config)
        self.assertEqual(final.metrics['config_suppressed_findings'], 2)
        self.assertEqual(final.ai_review.findings, [])
        self.assertEqual(apply_review_config(final, config).metrics['config_suppressed_findings'], 2)

    def test_cli_forwards_explicit_config_and_network_opt_in(self):
        from repo_review_agent.analyzer import analyze_repository
        from repo_review_agent.cli import main

        with TemporaryDirectory() as tmp:
            report = analyze_repository(Path(tmp))
            with patch('repo_review_agent.cli.run_review', return_value=report) as run, patch('builtins.print'):
                self.assertEqual(main([tmp, '--config', str(Path(tmp) / 'policy.json'), '--vulnerability-scan']), 0)
                self.assertTrue(run.call_args.kwargs['vulnerability_scan'])
                self.assertEqual(run.call_args.kwargs['config_path'], Path(tmp) / 'policy.json')

    def test_missing_default_is_empty_and_explicit_missing_fails(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(load_review_config(root).ignore, [])
            with self.assertRaises(ValueError):
                load_review_config(root, root / 'missing.json')

    def test_config_strictly_rejects_execution_unknown_types_and_oversize(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / '.repo-review.json'
            for value in ({'run_linters': True}, {'ignore': 'src'}, {'ignore': ['../outside']},
                          {'disabled_rules': [1]}, {'severity_overrides': {'x': 'critical'}}, []):
                path.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_review_config(root)
            path.write_text(' ' * 65537)
            with self.assertRaises(ValueError):
                load_review_config(root)

    def test_symlink_config_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'actual.json').write_text('{}')
            (root / '.repo-review.json').symlink_to(root / 'actual.json')
            with self.assertRaises(ValueError):
                load_review_config(root)

    def test_rule_ids_categories_and_ai_severities(self):
        finding = Finding('Specific package issue', 'medium', 'dependency vulnerabilities', [], '', rule_id='dependency.osv')
        ai = AIReview('fake', 'fake', 'generated', '', findings=[{'title': 'AI defect', 'severity': 'high', 'path': 'app.py'}])
        report = ReviewReport('repo', '', [], {}, {}, [finding], ai_review=ai)
        result = apply_review_config(report, ReviewConfig(disabled_categories=['code'], severity_overrides={'dependency.osv': 'high'}))
        self.assertEqual(result.findings[0].severity, 'high')
        self.assertEqual(result.ai_review.findings, [])
        result = apply_review_config(report, ReviewConfig(disabled_rules=['dependency.osv'], severity_overrides={'AI defect': 'info'}))
        self.assertEqual(result.findings, [])
        self.assertEqual(result.ai_review.findings[0]['severity'], 'info')

    def test_duplicate_keys_and_invalid_json_are_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / '.repo-review.json'
            for content in (b'{"ignore": [], "ignore": ["src"]}', b'{invalid', b'\xff'):
                path.write_bytes(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    load_review_config(root)

    def test_glob_matching_supports_nested_and_root_file_patterns(self):
        from repo_review_agent.config import path_is_ignored

        self.assertTrue(path_is_ignored('src/generated/app.py', ['**/generated/**']))
        self.assertTrue(path_is_ignored('app.test.py', ['**/*.test.py']))
        self.assertTrue(path_is_ignored('generated/app.py', ['generated/']))
        self.assertFalse(path_is_ignored('src/app.py', ['generated/**']))

    def test_config_filters_and_overrides_rules_and_ai_without_mutation(self):
        findings = [Finding('Remove me', 'high', 'security', [], '', ['src/a.py']),
                    Finding('Tune me', 'low', 'testing', [], '', ['src/b.py'])]
        ai = AIReview('fake', 'fake', 'generated', '', findings=[{
            'title': 'AI defect', 'severity': 'high', 'path': 'ignored/a.py',
            'evidence': 'bad', 'start_line': 1, 'end_line': 1,
        }])
        report = ReviewReport('repo', '', [], {}, {}, findings, ai_review=ai)
        config = ReviewConfig(ignore=['ignored/**'], disabled_rules=['Remove me'],
                              severity_overrides={'Tune me': 'medium'})
        filtered = apply_review_config(report, config)
        self.assertEqual([(f.title, f.severity) for f in filtered.findings], [('Tune me', 'medium')])
        self.assertEqual(filtered.ai_review.findings, [])
        self.assertEqual(report.findings[1].severity, 'low')
        self.assertEqual(len(report.ai_review.findings), 1)

    def test_scanner_ignores_globs_before_inventory_and_content_selection(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'generated').mkdir()
            (root / 'generated' / 'app.py').write_text('secret')
            (root / 'app.py').write_text('keep')
            (root / 'package-lock.json').write_text('{}')
            scan = scan_repository(root, ignore_patterns=['generated/**', '*lock.json'])
        self.assertEqual([f.path for f in scan.files], ['app.py'])
        self.assertEqual(scan.source_files, ['app.py'])
        self.assertNotIn('generated', scan.top_level_items)
