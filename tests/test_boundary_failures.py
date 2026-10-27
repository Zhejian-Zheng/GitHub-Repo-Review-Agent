"""Failure injection at public auth, storage and isolated-worker boundaries."""
import json
import os
import sys
import unittest
from http.client import IncompleteRead
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import HTTPException

from repo_review_agent import web
from repo_review_agent.auth import AuthError, get_supabase_user
from repo_review_agent.history import HistoryStoreError, SupabaseHistoryStore
from repo_review_agent.job_runtime import run_isolated
from repo_review_agent.security import InMemoryRateLimiter, request_token_matches


class Response(BytesIO):
    def __enter__(self):
        return self


class BoundaryFailureTests(unittest.TestCase):
    def test_auth_never_exposes_upstream_error_body_or_network_details(self):
        errors = [
            HTTPError('https://unused', 401, 'denied', {}, BytesIO(b'PRIVATE upstream token data')),
            TimeoutError('PRIVATE network address'),
            ConnectionResetError('PRIVATE connection details'),
            IncompleteRead(b'PRIVATE'),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch(
                'repo_review_agent.auth.urlopen', side_effect=error
            ), self.assertRaises(AuthError) as caught:
                get_supabase_user('token', supabase_url='https://unused', anon_key='key')
            self.assertNotIn('PRIVATE', str(caught.exception))

    def test_auth_rejects_invalid_json_shapes_and_encoding(self):
        for body in (b'[]', b'null', b'"text"', b'123', b'{', b'\xff'):
            with self.subTest(body=body), patch(
                'repo_review_agent.auth.urlopen', return_value=Response(body)
            ), self.assertRaises(AuthError):
                get_supabase_user('token', supabase_url='https://unused', anon_key='key')

    def test_storage_normalizes_transport_and_decode_failures(self):
        store = SupabaseHistoryStore(supabase_url='https://unused', service_key='key')
        for error in (TimeoutError('PRIVATE'), ConnectionResetError('PRIVATE'), IncompleteRead(b'PRIVATE')):
            with self.subTest(error=error), patch(
                'repo_review_agent.history.urlopen', side_effect=error
            ), self.assertRaises(HistoryStoreError) as caught:
                store._request('GET', 'repositories')
            self.assertNotIn('PRIVATE', str(caught.exception))
        for body in (b'<html>PRIVATE proxy failure</html>', b'\xff'):
            with self.subTest(body=body), patch(
                'repo_review_agent.history.urlopen', return_value=Response(body)
            ), self.assertRaises(HistoryStoreError) as caught:
                store._request('GET', 'repositories')
            self.assertNotIn('PRIVATE', str(caught.exception))

    def test_rotating_forwarding_headers_does_not_bypass_default_rate_limit(self):
        limiter = InMemoryRateLimiter(limit_per_minute=1)
        with patch.dict(os.environ, {}, clear=True), patch.object(web, 'WEB_RATE_LIMITER', limiter):
            for index in range(2):
                request = SimpleNamespace(headers={'x-real-ip': f'fake-{index}'},
                                          client=SimpleNamespace(host='peer'))
                if index == 0:
                    web.enforce_api_access_controls(request)
                else:
                    with self.assertRaises(HTTPException) as caught:
                        web.enforce_api_access_controls(request)
                    self.assertEqual(caught.exception.status_code, 429)

    def test_storage_gateway_failure_returns_safe_503_through_http(self):
        from fastapi.testclient import TestClient

        from repo_review_agent.auth import AuthUser

        store = SupabaseHistoryStore(supabase_url='https://unused', service_key='key')
        with patch.object(web, 'authenticated_user_from_request', return_value=AuthUser('owner')), patch.object(
            web.SupabaseHistoryStore, 'from_env', return_value=store
        ), patch('repo_review_agent.history.urlopen', return_value=Response(b'PRIVATE invalid JSON')), TestClient(web.create_app()) as client:
            response = client.get('/history/repositories')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE', response.text)

    def test_explicit_proxy_trust_uses_forwarding_headers(self):
        with patch.dict(os.environ, {'REPO_REVIEW_TRUST_FORWARDED_FOR': 'true'}, clear=True), patch.object(
            web, 'WEB_RATE_LIMITER'
        ) as limiter:
            web.enforce_api_access_controls(SimpleNamespace(
                headers={'x-real-ip': 'proxy-client'}, client=SimpleNamespace(host='proxy')
            ))
        limiter.allow.assert_called_once_with('proxy-client')

    def test_non_ascii_api_token_is_rejected_without_server_error(self):
        self.assertFalse(request_token_matches({'x-repo-review-token': 'é'}, 'secret'))
        self.assertFalse(request_token_matches({'authorization': 'Bearer é'}, 'secret'))

    def test_api_bearer_token_works_without_impersonating_a_supabase_user(self):
        request = SimpleNamespace(headers={'authorization': 'Bearer api-only'}, client=None)
        with patch.dict(os.environ, {'REPO_REVIEW_API_TOKEN': 'api-only'}, clear=True), patch.object(
            web, 'get_supabase_user', side_effect=AssertionError('API token is not a user JWT')
        ):
            self.assertIsNone(web.authenticated_user_from_request(request, required=False))
            web.enforce_api_access_controls(request)
            with self.assertRaises(HTTPException) as caught:
                web.authenticated_user_from_request(request, required=True)
            self.assertEqual(caught.exception.status_code, 401)

    def test_worker_rejects_corrupt_or_wrongly_shaped_results(self):
        for body in ('{', 'null', '[]', '{}', '{"result":null}', '{"result":[]}',
                     '{"error":123}', '{"error":"bad","result":{}}'):
            code = (
                "import os,pathlib; "
                f"pathlib.Path(os.environ['TMPDIR'],'output.json').write_text({body!r})"
            )
            with self.subTest(body=body), self.assertRaisesRegex(RuntimeError, 'invalid result'):
                run_isolated({}, None, timeout=5, command=[sys.executable, '-c', code])

    def test_worker_cannot_succeed_after_nonzero_exit(self):
        code = (
            "import os,pathlib; "
            "pathlib.Path(os.environ['TMPDIR'],'output.json').write_text('{\"result\":{}}'); "
            "raise SystemExit(1)"
        )
        with self.assertRaisesRegex(RuntimeError, 'exited unsuccessfully'):
            run_isolated({}, None, timeout=5, command=[sys.executable, '-c', code])

    def test_invalid_recovered_request_does_not_persist_validation_input(self):
        from unittest.mock import Mock

        storage = Mock()
        storage.claim_job.side_effect = [
            {'id': 'bad', 'request_json': {'target': '.', 'max_files': 'PRIVATE input'}}, None
        ]
        store = web.SupabaseBackedReviewJobStore(storage=storage)
        self.addCleanup(store.shutdown)
        store.sweep()
        payload = storage.write_claimed_job.call_args.kwargs
        self.assertEqual(payload['status'], 'failed')
        self.assertNotIn('PRIVATE', json.dumps(payload))
        self.assertEqual(store._leases, {})
