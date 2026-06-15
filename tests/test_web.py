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

    @patch("repo_review_agent.web.RepoReviewAgent")
    def test_run_review_for_path_supports_agent_mode(self, mock_agent_class) -> None:
        from repo_review_agent.models import ReviewReport
        from repo_review_agent.web import ReviewRequest, run_review_for_path

        expected = ReviewReport(
            repo_name="agent",
            generated_at="2026-05-28T00:00:00+00:00",
            overview=[],
            metrics={},
            framework_signals={},
            findings=[],
        )
        mock_agent_class.return_value.run.return_value = expected

        request = ReviewRequest(target=".", mode="agent", ai_provider="ollama", ai_model="llama")
        report = run_review_for_path(request, Path("."))

        self.assertIs(report, expected)
        mock_agent_class.assert_called_once()

    @patch("repo_review_agent.web.OpenAIFunctionCallingAgent")
    def test_run_review_for_path_supports_function_calling_mode(self, mock_agent_class) -> None:
        from repo_review_agent.models import ReviewReport
        from repo_review_agent.web import ReviewRequest, run_review_for_path

        expected = ReviewReport(
            repo_name="functions",
            generated_at="2026-05-28T00:00:00+00:00",
            overview=[],
            metrics={},
            framework_signals={},
            findings=[],
        )
        mock_agent_class.return_value.run.return_value = expected

        request = ReviewRequest(target=".", mode="function-calling", ai_model="gpt-test")
        report = run_review_for_path(request, Path("."))

        self.assertIs(report, expected)
        mock_agent_class.assert_called_once()

    @patch("repo_review_agent.web.add_ai_review")
    def test_run_review_for_path_attaches_ai_error_for_direct_mode(self, mock_add_ai_review) -> None:
        from repo_review_agent.llm import AIProviderError
        from repo_review_agent.web import ReviewRequest, run_review_for_path

        mock_add_ai_review.side_effect = AIProviderError("offline")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            request = ReviewRequest(target=str(root), mode="direct", ai_provider="ollama")

            report = run_review_for_path(request, root)

        self.assertIsNotNone(report.ai_review)
        self.assertEqual(report.ai_review.status, "error")
        self.assertIn("offline", report.ai_review.error)

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

    def test_public_api_controls_rate_limits_clients(self) -> None:
        from fastapi import HTTPException

        from repo_review_agent.web import enforce_public_api_controls

        with (
            patch.dict("os.environ", {"REPO_REVIEW_API_TOKEN": ""}, clear=False),
            patch("repo_review_agent.web.WEB_RATE_LIMITER") as limiter,
            self.assertRaises(HTTPException) as context,
        ):
            limiter.allow.return_value = False
            enforce_public_api_controls(
                _fake_request(headers={}),
                "https://github.com/owner/repo",
            )

        self.assertEqual(context.exception.status_code, 429)

    def test_review_endpoint_returns_markdown_and_handles_errors(self) -> None:
        from fastapi import HTTPException

        from repo_review_agent.web import ReviewRequest, create_app

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            app = create_app()
            endpoint = _route_endpoint(app, "/review")

            with patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "true", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ):
                response = endpoint(
                    _fake_request(headers={}),
                    ReviewRequest(target=str(root), mode="direct"),
                )
                with self.assertRaises(HTTPException) as context:
                    endpoint(
                        _fake_request(headers={}),
                        ReviewRequest(target=str(root / "missing")),
                    )

        self.assertIn("markdown", response)
        self.assertEqual(context.exception.status_code, 400)

    def test_index_uses_fallback_or_built_frontend(self) -> None:
        import repo_review_agent.web as web

        with TemporaryDirectory() as tmp:
            missing_dist = Path(tmp) / "missing-dist"
            with (
                patch.object(web, "FRONTEND_DIST", missing_dist),
                patch.object(web, "FRONTEND_INDEX", missing_dist / "index.html"),
                patch.object(web, "FRONTEND_ASSETS", missing_dist / "assets"),
            ):
                fallback_response = _route_endpoint(web.create_app(), "/")()
        self.assertIn(b"React frontend has not been built", fallback_response.body)

        with TemporaryDirectory() as tmp:
            dist = Path(tmp)
            assets = dist / "assets"
            assets.mkdir()
            (dist / "index.html").write_text("<!doctype html><title>Built</title>", encoding="utf-8")

            with (
                patch.object(web, "FRONTEND_DIST", dist),
                patch.object(web, "FRONTEND_INDEX", dist / "index.html"),
                patch.object(web, "FRONTEND_ASSETS", assets),
            ):
                built_response = _route_endpoint(web.create_app(), "/")()

        self.assertEqual(Path(built_response.path), dist / "index.html")

    def test_main_starts_uvicorn(self) -> None:
        import repo_review_agent.web as web

        with patch.object(web.uvicorn, "run") as mock_run:
            web.main()

        mock_run.assert_called_once_with(
            "repo_review_agent.web:create_app",
            factory=True,
            host="0.0.0.0",
            port=8000,
        )


def _fake_request(headers: dict[str, str]):
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host="127.0.0.1"))


def _route_endpoint(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


if __name__ == "__main__":
    unittest.main()
