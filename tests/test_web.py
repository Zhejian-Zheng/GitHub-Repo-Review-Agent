import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(HAS_FASTAPI, "FastAPI test dependency is not installed")
class WebAPITests(unittest.TestCase):
    def test_run_review_for_path_returns_markdown_and_report(self) -> None:
        from repo_review_agent.web import ReviewRequest, run_review_for_path

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Example\n\n## Usage\nRun python -m unittest.\n\n## Demo\nExample output.\n",
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (root / ".gitignore").write_text(".venv\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

            request = ReviewRequest(target=str(root), mode="direct")
            report = run_review_for_path(request, root)

        self.assertEqual(report.repo_name, Path(tmp).name)
        self.assertTrue(report.findings)

    def test_public_api_controls_require_token_when_configured(self) -> None:
        from fastapi import HTTPException

        from repo_review_agent.web import enforce_public_api_controls

        with (
            patch.dict("os.environ", {"REPO_REVIEW_API_TOKEN": "secret"}, clear=False),
            self.assertRaises(HTTPException) as context,
        ):
            enforce_public_api_controls(
                _fake_request(headers={}),
                "https://github.com/owner/repo",
            )

        self.assertEqual(context.exception.status_code, 401)

    def test_public_api_controls_reject_local_target_in_public_mode(self) -> None:
        from fastapi import HTTPException

        from repo_review_agent.web import enforce_public_api_controls

        with (
            patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "false", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ),
            self.assertRaises(HTTPException) as context,
        ):
            enforce_public_api_controls(_fake_request(headers={}), ".")

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("only allows GitHub", context.exception.detail)


def _fake_request(headers: dict[str, str]):
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host="127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
