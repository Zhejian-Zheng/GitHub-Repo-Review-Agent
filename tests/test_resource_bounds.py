"""Resource breaches fail before parsing or retaining attacker-controlled bodies."""
import asyncio
import json
import threading
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from repo_review_agent import web
from repo_review_agent.auth import AuthError, get_supabase_user
from repo_review_agent.history import HistoryStoreError, SupabaseHistoryStore


class ResourceBoundsTests(unittest.TestCase):
    def test_oversized_credential_responses_are_safe_and_bounded(self) -> None:
        # Valid JSON must still be rejected, without consuming the entire response.
        body = json.dumps({'id': 'user', 'padding': 'PRIVATE' * 1_500_000}).encode()
        for module, invoke, error in (
            ('auth', lambda: get_supabase_user('synthetic', supabase_url='https://unused', anon_key='key'), AuthError),
            ('history', lambda: SupabaseHistoryStore(supabase_url='https://unused', service_key='key')._request('GET', 'repositories'), HistoryStoreError),
        ):
            with self.subTest(module=module):
                response = BytesIO(body)
                with patch(f'repo_review_agent.{module}.urlopen') as opener:
                    opener.return_value.__enter__.return_value = response
                    with self.assertRaises(error) as caught:
                        invoke()
                    self.assertLess(response.tell(), len(body))
                    self.assertNotIn('PRIVATE', str(caught.exception))

    def test_ingress_rejects_declared_and_streamed_overflow_before_json(self) -> None:
        async def exercise(headers: list, chunks: list[bytes], expected_reads: int) -> None:
            sent = []
            receive = Mock(side_effect=[{'type': 'http.request', 'body': chunk, 'more_body': True} for chunk in chunks])

            async def read() -> dict:
                return receive()

            async def send(message: dict) -> None:
                sent.append(message)

            app = web.create_app()
            await app({'type': 'http', 'method': 'POST', 'path': '/review/questions',
                       'headers': headers, 'query_string': b'', 'http_version': '1.1',
                       'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1)}, read, send)
            self.assertEqual(sent[0]['status'], 413)
            self.assertEqual(receive.call_count, expected_reads)

        asyncio.run(exercise([(b'content-length', b'999999999')], [], 0))
        # Deliberately dishonest Content-Length must not bypass streaming checks.
        for headers in ([], [(b'content-length', b'1')]):
            asyncio.run(exercise(headers, [b' ' * 150_000] * 20, 2))

    def test_bounded_reader_handles_short_reads_and_exact_limit(self) -> None:
        from repo_review_agent.http import ResponseTooLargeError, read_response_bytes

        class ShortReads(BytesIO):
            def read(self, size: int = -1) -> bytes:
                self.assert_bounded(size)
                return super().read(min(size, 2))

            @staticmethod
            def assert_bounded(size: int) -> None:
                if size < 0:
                    raise AssertionError('unbounded read')

        self.assertEqual(read_response_bytes(ShortReads(b'abcd'), limit=4), b'abcd')
        stream = ShortReads(b'abcdefghi')
        with self.assertRaises(ResponseTooLargeError):
            read_response_bytes(stream, limit=4)
        self.assertEqual(stream.tell(), 5)

    def test_ingress_accepts_bounded_json_and_keeps_report_semantic_limit(self) -> None:
        from fastapi.testclient import TestClient

        with patch.object(web, 'authenticated_user_from_request', return_value=None), patch.object(
            web, 'enforce_api_access_controls'
        ), TestClient(web.create_app()) as client:
            # This fits ingress but still exceeds the existing 200 KB report limit.
            response = client.post('/review/questions', json={
                'question': 'Why?', 'provider': 'none', 'report': {'padding': 'x' * 200_001},
            })
            self.assertEqual(response.status_code, 422)
            for path in ('/review', '/review/jobs', '/review/questions'):
                response = client.post(path, content=b'{}', headers={'content-length': 'invalid'})
                self.assertEqual(response.status_code, 413)

    def test_oversized_github_success_and_error_responses_are_bounded(self) -> None:
        from urllib.error import HTTPError

        from repo_review_agent.github import GitHubClient, GitHubIntegrationError

        client = GitHubClient(token='synthetic')
        with patch('repo_review_agent.github.urlopen', return_value=BytesIO(b' ' * 8_000_001)), self.assertRaisesRegex(
            GitHubIntegrationError, 'byte limit'
        ):
            client._request_json('GET', '/unused')
        body = BytesIO(b'PRIVATE' * 2_000_000)
        error = HTTPError('https://unused', 503, 'unavailable', {}, body)
        with patch('repo_review_agent.github.urlopen', side_effect=error), self.assertRaises(GitHubIntegrationError) as caught:
            client._request_json('GET', '/unused')
        self.assertTrue(body.closed)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_blocked_cancellation_poll_cannot_accumulate_monitors(self) -> None:
        import sys
        import time

        from repo_review_agent import job_runtime

        entered, release = threading.Event(), threading.Event()
        slots = threading.BoundedSemaphore(1)

        def blocked() -> bool:
            entered.set()
            release.wait(5)
            return True

        command = [sys.executable, '-c', 'import time; time.sleep(10)']
        try:
            with patch.object(job_runtime, '_CANCELLATION_SLOTS', slots):
                start = time.monotonic()
                with self.assertRaisesRegex(RuntimeError, 'deadline'):
                    job_runtime.run_isolated({}, None, timeout=0.4, cancelled=blocked, command=command)
                self.assertTrue(entered.is_set())
                self.assertLess(time.monotonic() - start, 2)
                with self.assertRaisesRegex(RuntimeError, 'monitor capacity'):
                    job_runtime.run_isolated({}, None, timeout=5, cancelled=blocked, command=command)
        finally:
            release.set()
        self.assertTrue(slots.acquire(timeout=2))
        slots.release()
