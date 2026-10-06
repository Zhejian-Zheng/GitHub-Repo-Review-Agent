import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError

from repo_review_agent.vulnerabilities import scan_vulnerabilities


class VulnerabilityTests(unittest.TestCase):
    def test_invalid_python_versions_and_markers_do_not_claim_clean_coverage(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('\n'.join([
                'invalid==1garbage', 'broken==1..0', 'marker==1.0; nonsense',
                'valid[extra]==v1.0RC1; python_version < "3.12" # comment',
            ]))
            def respond(request, timeout):
                self.assertEqual(json.loads(request.data)['queries'], [
                    {'package': {'ecosystem': 'PyPI', 'name': 'valid'}, 'version': '1.0rc1'}])
                return io.BytesIO(b'{"results":[{}]}')
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checked_packages, 1)

    def test_invalid_npm_semver_is_not_reported_as_checked_registry_versions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            versions = ['01.2.3', '1.02.3', '1.2.03', '١.2.3', '1.2.3-beta..1',
                        '1.2.3-01', '1.2.3+build..1', '1.2.3-beta.1+build.01']
            (root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {
                f'node_modules/package{i}': {'version': version} for i, version in enumerate(versions)
            }}))
            def respond(request, timeout):
                self.assertEqual(json.loads(request.data)['queries'], [
                    {'package': {'ecosystem': 'npm', 'name': 'package7'}, 'version': '1.2.3-beta.1+build.01'}])
                return io.BytesIO(b'{"results":[{}]}')
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checked_packages, 1)

    def test_malformed_npm_entries_do_not_hide_valid_versions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {
                'node_modules/valid': {'version': '1.2.3'},
                'node_modules/object': [],
                'node_modules/bad-name': {'name': 'user:password@host/pkg', 'version': '1.2.3'},
                'node_modules/bad-version': {'version': '^1.2.3'},
                'node_modules/bad-resolved': {'version': '1.2.3', 'resolved': 17},
            }}))
            def respond(request, timeout):
                self.assertEqual(json.loads(request.data)['queries'], [
                    {'package': {'ecosystem': 'npm', 'name': 'valid'}, 'version': '1.2.3'}])
                return io.BytesIO(b'{"results":[{}]}')
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checked_packages, 1)
        self.assertNotIn('password', str(result))

    def test_unsupported_requirements_are_disclosed_without_network_or_credentials(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('\n'.join([
                '# comment', '', 'example>=1.0', 'example==1.*', '-r private.txt',
                'example @ https://user:password@example.org/package.whl',
                'example==file:../local', 'x' * 215 + '==1.0', 'example==' + '1' * 101,
            ]))
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=AssertionError('network forbidden')):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(result.total_packages, 0)
        self.assertTrue(any('not exact supported versions' in detail for detail in result.details))
        self.assertNotIn('password', str(result))

    def test_dependency_file_cap_discloses_unchecked_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for number in range(21):
                (root / f'requirements-{number:02d}.txt').write_text(f'package{number}==1.0')
            def respond(request, timeout):
                queries = json.loads(request.data)['queries']
                self.assertEqual(len(queries), 20)
                self.assertNotIn({'package': {'ecosystem': 'PyPI', 'name': 'package20'}, 'version': '1.0'}, queries)
                return io.BytesIO(json.dumps({'results': [{}] * 20}).encode())
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checked_packages, 20)
        self.assertTrue(any('first 20' in detail for detail in result.details))

    def test_advisory_truncation_preserves_bounded_evidence_and_partial_status(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('example==1.0')
            response = {'results': [{'vulns': [{'id': f'PYSEC-2020-{i:02d}'} for i in range(21)]}]}
            with patch('repo_review_agent.vulnerabilities.urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.findings[0].evidence), 20)
        self.assertTrue(result.findings[0].evidence[0].endswith('/PYSEC-2020-00'))
        self.assertTrue(result.findings[0].evidence[-1].endswith('/PYSEC-2020-19'))
        self.assertTrue(any('20 IDs' in detail for detail in result.details))

    def test_oversized_npm_identity_does_not_prevent_valid_packages_being_checked(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {
                'node_modules/valid': {'version': '1.2.3'},
                'node_modules/long-version': {'version': '1.2.3-' + 'a' * 100_000},
                'node_modules/long-scope': {'name': '@' + 's' * 100_000 + '/pkg', 'version': '1.2.3'},
            }}))
            def respond(request, timeout):
                self.assertEqual(json.loads(request.data)['queries'], [
                    {'package': {'ecosystem': 'npm', 'name': 'valid'}, 'version': '1.2.3'}])
                return io.BytesIO(b'{"results":[{}]}')
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checked_packages, 1)
        self.assertEqual(result.total_packages, 1)

    def test_npm_file_and_git_sources_do_not_claim_registry_version_checked(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {
                'node_modules/file-alias': {'name': 'example', 'version': '1.2.3', 'resolved': 'file:../example'},
                'node_modules/git-alias': {'version': '1.2.3', 'resolved': 'git+https://token@example.com/repo.git#abc'},
            }}))
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=AssertionError('network forbidden')):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(result.checked_packages, 0)
        self.assertNotIn('token', str(result))

    def test_supported_npm_versions_include_scopes_aliases_and_nested_dependencies(self):
        for lock_version in (2, 3):
            with self.subTest(lock_version=lock_version), TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': lock_version, 'packages': {
                    '': {'name': 'project'},
                    'node_modules/a/node_modules/alias': {'name': '@scope/real', 'version': '1.2.3-beta.1'},
                    'node_modules/workspace': {'link': True},
                }}))
                def respond(request, timeout):
                    self.assertEqual(json.loads(request.data)['queries'], [
                        {'package': {'ecosystem': 'npm', 'name': '@scope/real'}, 'version': '1.2.3-beta.1'}])
                    return io.BytesIO(b'{"results":[{"vulns":[{"id":"GHSA-abcd"}]}]}')
                with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                    result = scan_vulnerabilities(root)
                self.assertEqual(result.status, 'partial')
                self.assertEqual(result.findings[0].rule_id, 'dependency.osv')

    def test_invalid_and_oversized_locks_do_not_trigger_network(self):
        for content in ('[]', '{broken', '{"lockfileVersion":1}', 'x' * 2_097_153):
            with self.subTest(length=len(content)), TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'package-lock.json').write_text(content)
                with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=AssertionError('network forbidden')):
                    result = scan_vulnerabilities(root)
                self.assertEqual(result.status, 'unavailable')
                self.assertTrue(result.details)

    def test_failed_later_batch_retains_prior_advisories_and_partial_status(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('\n'.join(f'package{i}==1.0' for i in range(101)))
            response = {'results': [{'vulns': [{'id': 'PYSEC-2020-1'}]}] + [{}] * 99}
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=[
                io.BytesIO(json.dumps(response).encode()), URLError('unavailable'),
            ]):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.checked_packages, 100)
        self.assertEqual(len(result.findings), 1)

    def test_advisory_ids_are_validated_before_becoming_report_links(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('example==1.0')
            with patch('repo_review_agent.vulnerabilities.urlopen', return_value=io.BytesIO(
                b'{"results":[{"vulns":[{"id":"../../bad\\nheading"}]}]}'
            )):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'unavailable')
        self.assertFalse(result.findings)

    def test_exact_versions_query_osv_and_report_advisory_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('Django==2.2.0\nrequests>=2\n')
            (root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {
                '': {'name': 'project'}, 'node_modules/@scope/pkg': {'version': '1.2.3'},
            }}))
            def respond(request, timeout):
                queries = json.loads(request.data)['queries']
                self.assertEqual(queries, [
                    {'package': {'ecosystem': 'PyPI', 'name': 'django'}, 'version': '2.2.0'},
                    {'package': {'ecosystem': 'npm', 'name': '@scope/pkg'}, 'version': '1.2.3'},
                ])
                self.assertLessEqual(timeout, 10)
                return io.BytesIO(b'{"results":[{"vulns":[{"id":"PYSEC-2020-1"}]},{}]}')
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.findings), 1)
        self.assertIn('PYSEC-2020-1', result.findings[0].evidence[0])
        self.assertEqual(result.findings[0].evidence_paths, ['requirements.txt'])

    def test_network_and_malformed_responses_never_report_clean(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('example==1.0\n')
            for response in (b'{}', b'{"results":[]}', b'{"results":[{"vulns":null}]}', b'{"results":[{"error":"bad"}]}', b'x' * 1_048_577):
                with self.subTest(response_size=len(response)), patch(
                    'repo_review_agent.vulnerabilities.urlopen', return_value=io.BytesIO(response)
                ):
                    self.assertEqual(scan_vulnerabilities(root).status, 'unavailable')
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=URLError('secret backend')):
                result = scan_vulnerabilities(root)
                self.assertEqual(result.status, 'unavailable')
                self.assertNotIn('secret backend', str(result))

    def test_ignored_and_symlink_lockfiles_are_never_queried(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('example==1.0')
            (root / 'requirements-dev.txt').symlink_to(root / 'requirements.txt')
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=AssertionError('network forbidden')):
                result = scan_vulnerabilities(root, ignore_patterns=['requirements.txt'])
        self.assertEqual(result.status, 'unavailable')

    def test_empty_success_is_clean_but_server_pagination_is_partial(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('example==1.0')
            for body, status in ((b'{"results":[{}]}', 'clean'),
                                 (b'{"results":[{"next_page_token":"more"}]}', 'partial')):
                with patch('repo_review_agent.vulnerabilities.urlopen', return_value=io.BytesIO(body)):
                    self.assertEqual(scan_vulnerabilities(root).status, status)

    def test_batches_and_package_cap_are_bounded_and_explicit(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('\n'.join(f'package{i}==1.0' for i in range(501)))
            requests = []
            def respond(request, timeout):
                queries = json.loads(request.data)['queries']
                requests.append(queries)
                return io.BytesIO(json.dumps({'results': [{} for _ in queries]}).encode())
            with patch('repo_review_agent.vulnerabilities.urlopen', side_effect=respond):
                result = scan_vulnerabilities(root)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(requests), 5)
        self.assertTrue(all(len(batch) == 100 for batch in requests))
