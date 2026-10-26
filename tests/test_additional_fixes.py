import json
import os
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from repo_review_agent.analyzer import analyze_repository
from repo_review_agent.auth import AuthUser
from repo_review_agent.scanner import scan_repository
from repo_review_agent.service import run_review
from repo_review_agent.web import AuthTokenCache


class AdditionalFixTests(unittest.TestCase):
    def test_colocated_javascript_tests_are_not_reported_missing(self):
        for suffix in ('.test.js', '.test.jsx', '.spec.js', '.spec.jsx'):
            with self.subTest(suffix=suffix), TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'app.js').write_text('export const value = 1;')
                (root / ('app' + suffix)).write_text('test("value", () => {});')
                snapshot = scan_repository(root)
                self.assertEqual(snapshot.test_files, ['app' + suffix])
                self.assertEqual(snapshot.source_files, ['app.js'])
                report = analyze_repository(root)
                self.assertFalse(any(f.title == 'Add automated tests for the core behavior' for f in report.findings))

    @unittest.skipUnless(shutil.which('ruff') or Path('.venv/bin/ruff').exists(), 'Ruff required')
    def test_linter_uses_only_sampled_allowed_files_without_modifying_them(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'PATH': str(Path('.venv/bin').resolve()) + os.pathsep + os.environ['PATH']}):
            root = Path(tmp)
            for name in ('fixtures', 'vendor'):
                (root / name).mkdir()
                (root / name / 'bad.py').write_text('missing_name()\n')
            (root / 'app.py').write_text('missing_app()\n')
            (root / '.repo-review.json').write_text(json.dumps({'ignore': ['vendor/**']}))
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            report = run_review(root, mode='direct', run_linters=True, trust_repository_config=True)
            lint = [f for f in report.findings if 'Ruff F821' in f.title]
            self.assertEqual(len(lint), 1)
            self.assertEqual(lint[0].evidence_paths, ['app.py'])
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            limited = run_review(root, mode='direct', max_files=0, run_linters=True)
            self.assertFalse(any('Ruff F821' in f.title for f in limited.findings))

    def test_cache_reclaims_expired_entries_without_revisiting_tokens(self):
        cache = AuthTokenCache(ttl_seconds=1)
        user = AuthUser('owner')
        for i in range(1000):
            cache.set(str(i), user, now=0)
        cache.set('current', user, now=100)
        self.assertEqual(len(cache._entries), 1)
        self.assertEqual(cache.get('current', now=100), user)
        self.assertIsNone(cache.get('current', now=102))

    def test_cache_capacity_is_bounded_during_concurrent_writes(self):
        cache = AuthTokenCache(ttl_seconds=60, max_entries=10)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: cache.set(str(i), AuthUser('owner'), now=0), range(100)))
        self.assertLessEqual(len(cache._entries), 10)
        cache.set('latest', AuthUser('owner'), now=0)
        self.assertIsNotNone(cache.get('latest', now=0))

    @unittest.skipUnless(shutil.which('ruff') or Path('.venv/bin/ruff').exists(), 'Ruff required')
    def test_remaining_python_stub_is_still_checked_after_source_deletion(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'PATH': str(Path('.venv/bin').resolve()) + os.pathsep + os.environ['PATH']}):
            root = Path(tmp)
            (root / 'app.py').write_text('pass\n')
            (root / 'api.pyi').write_text('x: UndefinedName\n')
            before = run_review(root, mode='direct', run_linters=True)
            self.assertTrue(any('Ruff F821' in f.title for f in before.findings))
            (root / 'app.py').unlink()
            after = run_review(root, mode='direct', run_linters=True)
            self.assertTrue(any('Ruff F821' in f.title for f in after.findings))
