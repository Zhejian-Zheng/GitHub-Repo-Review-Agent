import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from repo_review_agent.requests import ReviewRequest


class ReviewRequestLimitTests(unittest.TestCase):
    def test_omitted_scan_limits_respect_environment_caps(self) -> None:
        with patch.dict(os.environ, {
            "REPO_REVIEW_MAX_FILES_LIMIT": "120",
            "REPO_REVIEW_MAX_FILE_SIZE_LIMIT": "4096",
        }, clear=False):
            request = ReviewRequest(target=".")

        self.assertEqual(request.max_files, 120)
        self.assertEqual(request.max_file_size, 4096)

    def test_explicit_scan_limits_are_rejected_before_admission(self) -> None:
        with patch.dict(os.environ, {
            "REPO_REVIEW_MAX_FILES_LIMIT": "120",
            "REPO_REVIEW_MAX_FILE_SIZE_LIMIT": "4096",
        }, clear=False):
            self.assertEqual(ReviewRequest(target=".", max_files=120).max_files, 120)
            with self.assertRaises(ValidationError):
                ReviewRequest(target=".", max_files=121)
            with self.assertRaises(ValidationError):
                ReviewRequest(target=".", max_file_size=4097)

    def test_defaults_keep_the_public_contract_when_caps_are_high(self) -> None:
        with patch.dict(os.environ, {
            "REPO_REVIEW_MAX_FILES_LIMIT": "1000",
            "REPO_REVIEW_MAX_FILE_SIZE_LIMIT": "1000000",
        }, clear=False):
            request = ReviewRequest(target=".")

        self.assertEqual(request.max_files, 500)
        self.assertEqual(request.max_file_size, 512_000)


if __name__ == "__main__":
    unittest.main()
