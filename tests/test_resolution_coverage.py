import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from repo_review_agent.analyzer import analyze_repository
from repo_review_agent.models import AIReview, Finding
from repo_review_agent.pr_bot import build_pr_bot_comment, build_pr_review_diff
from repo_review_agent.service import run_review


class ResolutionCoverageTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'README.md').write_text('# Project\nInstall and run. Example output.\n')
        self.source = self.root / 'app.py'
        self.source.write_text('api_key = "sk-' + 'a' * 32 + '"\n')
        self.before = analyze_repository(self.root)

    def test_partial_scan_keeps_missing_risk_unverified(self):
        after = analyze_repository(self.root, max_files=1)
        diff = build_pr_review_diff(after, self.before)
        self.assertFalse(any(f.category == 'security' for f in diff.resolved_findings))
        self.assertEqual([f.title for f in diff.unverified_findings], ['Remove possible hard-coded secrets'])
        self.assertIn('Not reverified', build_pr_bot_comment(diff))

    def test_full_recheck_and_deleted_source_can_resolve(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                if deleted:
                    self.source.unlink()
                else:
                    self.source.write_text('print("fixed")\n')
                diff = build_pr_review_diff(analyze_repository(self.root), self.before)
                self.assertTrue(any(f.category == 'security' for f in diff.resolved_findings))
                self.assertEqual(diff.unverified_findings, [])

    def test_unknown_coverage_cannot_claim_resolution(self):
        after = replace(self.before, findings=[], metrics={})
        diff = build_pr_review_diff(after, self.before)
        self.assertEqual(diff.resolved_findings, [])
        self.assertGreater(len(diff.unverified_findings), 0)

    def test_ai_omission_disabled_tools_and_changed_policy_are_not_fixes(self):
        after = run_review(self.root, mode='direct')
        candidates = [
            Finding('AI risk', 'high', 'code', ['x'], 'Fix', ['app.py'], source='ai'),
            Finding('Fix 1 Ruff F821 lint finding(s)', 'medium', 'correctness', ['x'], 'Fix', ['app.py']),
            Finding('Known vulnerabilities in x@1', 'medium', 'dependency vulnerabilities', ['x'], 'Fix', ['app.py'], rule_id='dependency.osv'),
        ]
        for finding in candidates:
            with self.subTest(title=finding.title):
                previous = replace(after, findings=[finding])
                diff = build_pr_review_diff(replace(after, ai_review=AIReview('openai', 'test', 'generated', '')), previous)
                self.assertNotIn(finding.title, [f.title for f in diff.resolved_findings])
                self.assertIn(finding.title, [f.title for f in diff.unverified_findings])
        self.source.write_text('print("fixed")\n')
        after = run_review(self.root, mode='direct')
        after = replace(after, metrics={**after.metrics, 'policy_config': {'ignore': ['vendor/**']}})
        self.assertEqual(build_pr_review_diff(after, self.before).resolved_findings, [])

    def test_internal_content_limits_cannot_claim_complete_recheck(self):
        self.source.write_text('#' * 80_001 + '\napi_key = "sk-' + 'a' * 32 + '"\n')
        diff = build_pr_review_diff(analyze_repository(self.root), self.before)
        self.assertFalse(any(f.category == 'security' for f in diff.resolved_findings))

    def test_all_risks_gate_retains_unverified_high_risk(self):
        from repo_review_agent.pr_bot import blocking_findings
        diff = build_pr_review_diff(analyze_repository(self.root, max_files=1), self.before)
        self.assertTrue(any(f.category == 'security' for f in blocking_findings(diff, fail_on_severity='high', scope='all')))
        self.assertEqual(blocking_findings(diff, fail_on_severity='high', scope='new'), [])

    def test_blank_ci_does_not_prove_tests_were_added(self):
        workflows = self.root / '.github' / 'workflows'
        workflows.mkdir(parents=True)
        ci = workflows / 'ci.yml'
        ci.write_text('steps:\n  - run: echo nothing\n')
        before = analyze_repository(self.root)
        ci.write_text('')
        diff = build_pr_review_diff(analyze_repository(self.root), before)
        self.assertNotIn('Run automated tests in CI', [f.title for f in diff.resolved_findings])

    def test_malformed_manifest_does_not_prove_dependencies_were_pinned(self):
        manifest = self.root / 'package.json'
        manifest.write_text('{"dependencies":{"lib":"*"}}')
        before = analyze_repository(self.root)
        manifest.write_text('{')
        diff = build_pr_review_diff(analyze_repository(self.root), before)
        self.assertNotIn('Pin broad or floating dependency versions', [f.title for f in diff.resolved_findings])

    def test_docker_checker_does_not_skip_later_files_after_first_risk(self):
        (self.root / 'z.Dockerfile').write_text('FROM python:latest\nUSER app\n')
        before = analyze_repository(self.root)
        (self.root / 'a.Dockerfile').write_text('FROM python:3.12\n')
        after = analyze_repository(self.root)
        self.assertTrue(any(f.title == 'Pin Docker base image versions' and 'z.Dockerfile' in f.evidence_paths for f in after.findings))
        self.assertNotIn('Pin Docker base image versions', [f.title for f in build_pr_review_diff(after, before).resolved_findings])

    def test_failed_or_truncated_read_remains_incomplete_after_later_success(self):
        from repo_review_agent.scanner import read_text_file, track_incomplete_reads
        with track_incomplete_reads() as incomplete:
            read_text_file(self.root, 'app.py', limit=1)
            read_text_file(self.root, 'app.py', limit=1000)
        self.assertIn('app.py', incomplete)

    def test_symlink_exclusion_does_not_establish_deletion(self):
        fixtures = self.root / 'fixtures'
        fixtures.mkdir()
        self.source.rename(fixtures / 'real.py')
        self.source.symlink_to(fixtures / 'real.py')
        diff = build_pr_review_diff(analyze_repository(self.root), self.before)
        self.assertFalse(any(f.category == 'security' for f in diff.resolved_findings))
        self.assertTrue(any(f.category == 'security' for f in diff.unverified_findings))

    def test_osv_excluded_symlink_is_partial_and_cannot_resolve_vulnerability(self):
        from unittest.mock import patch
        lock = self.root / 'requirements.txt'
        lock.write_text('badpkg==1.0\n')
        (self.root / 'requirements-other.txt').write_text('goodpkg==1.0\n')
        def query(packages):
            return [{'vulns': [{'id': 'TEST-1'}]} if name == 'badpkg' else {} for _, name, _ in packages]
        with patch('repo_review_agent.vulnerabilities._query_batch', side_effect=query):
            before = run_review(self.root, mode='direct', vulnerability_scan=True)
            fixtures = self.root / 'fixtures'
            fixtures.mkdir()
            lock.rename(fixtures / 'requirements.txt')
            lock.symlink_to(fixtures / 'requirements.txt')
            after = run_review(self.root, mode='direct', vulnerability_scan=True)
        self.assertEqual(after.metrics['vulnerability_scan']['status'], 'partial')
        diff = build_pr_review_diff(after, before)
        self.assertFalse(any(f.rule_id == 'dependency.osv' for f in diff.resolved_findings))
        self.assertTrue(any(f.rule_id == 'dependency.osv' for f in diff.unverified_findings))
