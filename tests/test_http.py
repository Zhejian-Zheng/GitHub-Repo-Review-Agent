"""Exercise the real urllib redirect policy with synthetic credentials."""
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request

from repo_review_agent.http import credential_urlopen


class CredentialHTTPTests(unittest.TestCase):
    def test_redirects_never_forward_credentials_or_replay_mutations(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path, self.headers.get('Authorization'), self.command))
                if self.path == '/destination':
                    self.send_response(200)
                else:
                    self.send_response(int(self.path[1:]))
                    self.send_header('Location', f'http://localhost:{self.server.server_port}/destination')
                self.end_headers()

            do_POST = do_GET

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for method in ('GET', 'POST'):
                for status in (301, 302, 303, 307, 308):
                    with self.subTest(method=method, status=status):
                        request = Request(
                            f'http://127.0.0.1:{server.server_port}/{status}',
                            headers={'Authorization': 'Bearer synthetic', 'apikey': 'synthetic'},
                            data=b'{}' if method == 'POST' else None, method=method,
                        )
                        with self.assertRaises(HTTPError) as caught:
                            credential_urlopen(request, timeout=2)
                        self.assertEqual(caught.exception.code, status)
                        caught.exception.close()
            self.assertEqual(len(received), 10)
            self.assertFalse(any(path == '/destination' for path, _, _ in received))
            self.assertTrue(all(token == 'Bearer synthetic' for _, token, _ in received))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
