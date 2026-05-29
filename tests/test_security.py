import os
import unittest
from unittest.mock import patch

from repo_review_agent.security import (
    InMemoryRateLimiter,
    bool_from_env,
    client_identifier,
    is_github_https_url,
    request_token_matches,
    validate_target_policy,
)


class SecurityTests(unittest.TestCase):
    @patch.dict(os.environ, {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "false"})
    def test_validate_target_policy_rejects_local_targets_in_public_mode(self) -> None:
        with self.assertRaises(ValueError):
            validate_target_policy(".")

        validate_target_policy("https://github.com/owner/repo")

    def test_github_url_validation_requires_github_owner_repo(self) -> None:
        self.assertTrue(is_github_https_url("https://github.com/owner/repo"))
        self.assertTrue(is_github_https_url("https://www.github.com/owner/repo.git"))
        self.assertFalse(is_github_https_url("git@github.com:owner/repo.git"))
        self.assertFalse(is_github_https_url("https://example.com/owner/repo"))
        self.assertFalse(is_github_https_url("https://github.com/owner"))

    @patch.dict(os.environ, {"FEATURE_FLAG": "yes"})
    def test_bool_from_env_handles_truthy_values(self) -> None:
        self.assertTrue(bool_from_env("FEATURE_FLAG", False))

    def test_request_token_matches_bearer_or_custom_header(self) -> None:
        self.assertTrue(request_token_matches({"authorization": "Bearer secret"}, "secret"))
        self.assertTrue(request_token_matches({"x-repo-review-token": "secret"}, "secret"))
        self.assertFalse(request_token_matches({"authorization": "Bearer wrong"}, "secret"))

    def test_client_identifier_prefers_forwarded_for(self) -> None:
        self.assertEqual(
            client_identifier({"x-forwarded-for": "203.0.113.1, 10.0.0.1"}, "127.0.0.1"),
            "203.0.113.1",
        )

    def test_rate_limiter_blocks_after_limit(self) -> None:
        limiter = InMemoryRateLimiter(limit_per_minute=2, window_seconds=60)

        self.assertTrue(limiter.allow("client", now=100))
        self.assertTrue(limiter.allow("client", now=101))
        self.assertFalse(limiter.allow("client", now=102))
        self.assertTrue(limiter.allow("client", now=161))


if __name__ == "__main__":
    unittest.main()
