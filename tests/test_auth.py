import os
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from repo_review_agent.auth import (
    AuthError,
    bearer_token_from_headers,
    get_supabase_user,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        return None

    def read(self) -> bytes:
        return self.body


class AuthTests(unittest.TestCase):
    def test_bearer_token_from_headers_extracts_token(self) -> None:
        self.assertEqual(bearer_token_from_headers({"authorization": "Bearer abc"}), "abc")
        self.assertIsNone(bearer_token_from_headers({"authorization": "Token abc"}))
        self.assertIsNone(bearer_token_from_headers({}))

    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "anon-key",
        },
        clear=True,
    )
    @patch("repo_review_agent.auth.urlopen")
    def test_get_supabase_user_verifies_token(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(b'{"id":"user-id","email":"user@example.com"}')

        user = get_supabase_user("access-token")

        self.assertEqual(user.id, "user-id")
        self.assertEqual(user.email, "user@example.com")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.supabase.co/auth/v1/user")
        self.assertEqual(request.get_header("Authorization"), "Bearer access-token")
        self.assertEqual(request.get_header("Apikey"), "anon-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_get_supabase_user_requires_configuration(self) -> None:
        with self.assertRaises(AuthError) as context:
            get_supabase_user("access-token")

        self.assertIn("SUPABASE_URL is required", str(context.exception))

        with self.assertRaises(AuthError) as key_context:
            get_supabase_user("access-token", supabase_url="https://example.supabase.co")

        self.assertIn("SUPABASE_ANON_KEY is required", str(key_context.exception))

    @patch("repo_review_agent.auth.urlopen")
    def test_get_supabase_user_wraps_auth_and_network_errors(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = HTTPError(
            "https://example.supabase.co/auth/v1/user",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b"bad token"),
        )

        with self.assertRaises(AuthError) as http_context:
            get_supabase_user(
                "bad-token",
                supabase_url="https://example.supabase.co",
                anon_key="anon-key",
            )

        self.assertIn("401", str(http_context.exception))
        self.assertIn("bad token", str(http_context.exception))

        mock_urlopen.side_effect = URLError("offline")
        with self.assertRaises(AuthError) as url_context:
            get_supabase_user(
                "token",
                supabase_url="https://example.supabase.co",
                anon_key="anon-key",
            )

        self.assertIn("offline", str(url_context.exception))

    @patch("repo_review_agent.auth.urlopen")
    def test_get_supabase_user_rejects_invalid_payload(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(b'{"email":"missing-id@example.com"}')

        with self.assertRaises(AuthError) as context:
            get_supabase_user(
                "token",
                supabase_url="https://example.supabase.co",
                anon_key="anon-key",
            )

        self.assertIn("user id", str(context.exception))


if __name__ == "__main__":
    unittest.main()
