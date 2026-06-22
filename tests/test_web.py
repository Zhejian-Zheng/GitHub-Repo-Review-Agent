import importlib.util
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(HAS_FASTAPI, "FastAPI test dependency is not installed")
class WebAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = patch.dict(
            "os.environ",
            {"REPO_REVIEW_JOB_STORE": "memory"},
            clear=False,
        )
        self._env_patcher.start()

        from repo_review_agent.web import WEB_AUTH_CACHE

        WEB_AUTH_CACHE.clear()

    def tearDown(self) -> None:
        self._env_patcher.stop()

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

    @patch("repo_review_agent.web.get_supabase_user")
    def test_authenticated_user_from_request_supports_required_login(self, mock_get_user) -> None:
        from fastapi import HTTPException

        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import authenticated_user_from_request

        mock_get_user.return_value = AuthUser(id="user-id", email="user@example.com")

        user = authenticated_user_from_request(
            _fake_request(headers={"authorization": "Bearer access-token"}),
            required=True,
        )

        self.assertEqual(user.id, "user-id")
        mock_get_user.assert_called_once_with("access-token")

        with self.assertRaises(HTTPException) as context:
            authenticated_user_from_request(_fake_request(headers={}), required=True)

        self.assertEqual(context.exception.status_code, 401)

    @patch("repo_review_agent.web.get_supabase_user")
    def test_authenticated_user_is_cached_within_ttl(self, mock_get_user) -> None:
        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import WEB_AUTH_CACHE, authenticated_user_from_request

        mock_get_user.return_value = AuthUser(id="user-id", email="user@example.com")
        request = _fake_request(headers={"authorization": "Bearer cached-token"})

        with patch.object(WEB_AUTH_CACHE, "ttl_seconds", 60):
            first = authenticated_user_from_request(request)
            second = authenticated_user_from_request(request)

        self.assertEqual(first.id, "user-id")
        self.assertEqual(second.id, "user-id")
        mock_get_user.assert_called_once_with("cached-token")

    @patch("repo_review_agent.web.get_supabase_user")
    def test_authenticated_user_not_cached_when_ttl_disabled(self, mock_get_user) -> None:
        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import WEB_AUTH_CACHE, authenticated_user_from_request

        mock_get_user.return_value = AuthUser(id="user-id")
        request = _fake_request(headers={"authorization": "Bearer no-cache-token"})

        with patch.object(WEB_AUTH_CACHE, "ttl_seconds", 0):
            authenticated_user_from_request(request)
            authenticated_user_from_request(request)

        self.assertEqual(mock_get_user.call_count, 2)

    def test_auth_token_cache_expires_entries(self) -> None:
        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import AuthTokenCache

        cache = AuthTokenCache(ttl_seconds=30)
        user = AuthUser(id="user-id")
        cache.set("tok", user, now=100)

        self.assertIsNotNone(cache.get("tok", now=120))
        self.assertIsNone(cache.get("tok", now=131))
        # Expired entry is evicted on access.
        self.assertIsNone(cache.get("tok", now=121))

    @patch("repo_review_agent.web.get_supabase_user")
    def test_auth_me_endpoint_returns_current_user(self, mock_get_user) -> None:
        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import create_app

        mock_get_user.return_value = AuthUser(id="user-id", email="user@example.com")

        endpoint = _route_endpoint(create_app(), "/auth/me")
        response = endpoint(_fake_request(headers={"authorization": "Bearer access-token"}))

        self.assertEqual(response, {"user": {"id": "user-id", "email": "user@example.com"}})

    def test_healthz_endpoint_returns_ok(self) -> None:
        from repo_review_agent.web import create_app

        endpoint = _route_endpoint(create_app(), "/healthz")

        self.assertEqual(endpoint(), {"status": "ok"})

    def test_create_app_configures_cors_from_environment(self) -> None:
        from repo_review_agent.web import create_app

        with patch.dict(
            "os.environ",
            {"REPO_REVIEW_CORS_ORIGINS": "https://example.github.io, https://demo.example.com/"},
            clear=False,
        ):
            app = create_app()

        middleware_classes = [middleware.cls.__name__ for middleware in app.user_middleware]
        self.assertIn("CORSMiddleware", middleware_classes)

    @patch("repo_review_agent.web.SupabaseReviewJobStore")
    def test_build_review_job_store_can_use_supabase(self, mock_storage_class) -> None:
        from repo_review_agent.web import SupabaseBackedReviewJobStore, build_review_job_store

        with patch.dict(
            "os.environ",
            {"REPO_REVIEW_JOB_STORE": "supabase"},
            clear=False,
        ):
            store = build_review_job_store()

        self.assertIsInstance(store, SupabaseBackedReviewJobStore)
        mock_storage_class.from_env.assert_called_once()

    @patch("repo_review_agent.web.SupabaseReviewJobStore")
    def test_build_review_job_store_auto_uses_supabase_when_configured(
        self,
        mock_storage_class,
    ) -> None:
        from repo_review_agent.web import SupabaseBackedReviewJobStore, build_review_job_store

        with patch.dict(
            "os.environ",
            {
                "REPO_REVIEW_JOB_STORE": "auto",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-key",
            },
            clear=False,
        ):
            store = build_review_job_store()

        self.assertIsInstance(store, SupabaseBackedReviewJobStore)
        mock_storage_class.from_env.assert_called_once()

    def test_build_review_job_store_auto_uses_memory_without_supabase(self) -> None:
        from repo_review_agent.web import InMemoryReviewJobStore, build_review_job_store

        with patch.dict("os.environ", {"REPO_REVIEW_JOB_STORE": "auto"}, clear=True):
            store = build_review_job_store()

        self.assertIsInstance(store, InMemoryReviewJobStore)

    @patch("repo_review_agent.web.execute_review_request")
    def test_supabase_backed_review_job_store_persists_completed_job(
        self,
        mock_execute_review,
    ) -> None:
        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import ReviewRequest, SupabaseBackedReviewJobStore

        mock_execute_review.return_value = {"markdown": "# Report", "report": {}}
        storage = _FakeSupabaseJobStorage()
        store = SupabaseBackedReviewJobStore(storage=storage, max_workers=1)
        store._executor = _ImmediateExecutor()  # noqa: SLF001

        submitted = store.submit(
            request=ReviewRequest(target="https://github.com/owner/repo", mode="direct"),
            user=AuthUser(id="user-id", email="user@example.com"),
        )
        completed = store.get(submitted.id)

        self.assertEqual(submitted.status, "queued")
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result["markdown"], "# Report")
        self.assertEqual(storage.created_payload["owner_id"], "user-id")
        self.assertEqual(storage.created_payload["request_json"]["mode"], "direct")
        self.assertEqual(storage.updated_statuses, ["running", "completed"])

    @patch("repo_review_agent.web.execute_review_request")
    def test_supabase_backed_review_job_store_marks_failed_jobs(self, mock_execute_review) -> None:
        from repo_review_agent.web import ReviewRequest, SupabaseBackedReviewJobStore

        mock_execute_review.side_effect = RuntimeError("broken")
        storage = _FakeSupabaseJobStorage()
        store = SupabaseBackedReviewJobStore(storage=storage, max_workers=1)
        store._executor = _ImmediateExecutor()  # noqa: SLF001

        submitted = store.submit(
            request=ReviewRequest(target="https://github.com/owner/repo", mode="direct"),
            user=None,
        )
        failed = store.get(submitted.id)

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "broken")
        self.assertEqual(storage.updated_statuses, ["running", "failed"])

    @patch("repo_review_agent.web.execute_review_request")
    def test_supabase_backed_review_job_store_ignores_failed_status_write_errors(
        self,
        mock_execute_review,
    ) -> None:
        from repo_review_agent.web import ReviewRequest, SupabaseBackedReviewJobStore

        mock_execute_review.side_effect = RuntimeError("broken")
        storage = _FakeSupabaseJobStorage(raise_on_failed_update=True)
        store = SupabaseBackedReviewJobStore(storage=storage, max_workers=1)

        store._run("job-id", ReviewRequest(target="https://github.com/owner/repo"), None)  # noqa: SLF001

        self.assertEqual(storage.updated_statuses, ["running", "failed"])

    def test_supabase_backed_review_job_store_handles_missing_and_stale_jobs(self) -> None:
        from repo_review_agent.web import SupabaseBackedReviewJobStore

        storage = _FakeSupabaseJobStorage()
        store = SupabaseBackedReviewJobStore(storage=storage, max_workers=1)

        self.assertIsNone(store.get("missing"))
        self.assertEqual(store.fail_stale_running_jobs(), 2)

    def test_job_from_supabase_row_validates_status_and_result(self) -> None:
        from repo_review_agent.history import HistoryStoreError
        from repo_review_agent.web import _job_from_supabase_row

        with self.assertRaises(HistoryStoreError):
            _job_from_supabase_row({"id": "job-id", "status": "paused"})

        with self.assertRaises(HistoryStoreError):
            _job_from_supabase_row(
                {
                    "id": "job-id",
                    "status": "completed",
                    "result_json": ["not", "an", "object"],
                }
            )

        job = _job_from_supabase_row(
            {
                "id": "job-id",
                "status": "failed",
                "owner_id": "user-id",
                "created_at": "created",
                "updated_at": "updated",
                "target": "https://github.com/owner/repo",
                "error": "nope",
            }
        )

        self.assertEqual(job.to_dict()["error"], "nope")

    @patch("repo_review_agent.web.execute_review_request")
    def test_in_memory_review_job_store_records_failed_jobs(self, mock_execute_review) -> None:
        from repo_review_agent.web import InMemoryReviewJobStore, ReviewRequest

        mock_execute_review.side_effect = RuntimeError("broken")
        store = InMemoryReviewJobStore(max_workers=1)

        submitted = store.submit(
            request=ReviewRequest(target="https://github.com/owner/repo", mode="direct"),
            user=None,
        )

        for _ in range(50):
            failed = store.get(submitted.id)
            if failed.status == "failed":
                break
            time.sleep(0.02)

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "broken")

        store._update("missing-job", status="failed", error="ignored")  # noqa: SLF001

    def test_create_app_startup_marks_stale_jobs_without_blocking_startup(self) -> None:
        from repo_review_agent.history import HistoryStoreError
        from repo_review_agent.web import create_app

        class StaleStore:
            def __init__(self) -> None:
                self.called = False

            def fail_stale_running_jobs(self) -> None:
                self.called = True
                raise HistoryStoreError("offline")

        store = StaleStore()
        with patch("repo_review_agent.web.build_review_job_store", return_value=store):
            app = create_app()
            _run_lifespan(app)

        self.assertTrue(store.called)

    def test_create_app_startup_allows_job_stores_without_stale_cleanup(self) -> None:
        from repo_review_agent.web import create_app

        with patch("repo_review_agent.web.build_review_job_store", return_value=object()):
            app = create_app()
            _run_lifespan(app)

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

    @patch("repo_review_agent.web.execute_review_request")
    def test_review_endpoint_maps_permission_errors_to_unauthorized(
        self,
        mock_execute_review,
    ) -> None:
        from fastapi import HTTPException

        from repo_review_agent.web import ReviewRequest, create_app

        mock_execute_review.side_effect = PermissionError("sign in")
        endpoint = _route_endpoint(create_app(), "/review")

        with (
            patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "true", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ),
            self.assertRaises(HTTPException) as context,
        ):
            endpoint(
                _fake_request(headers={}),
                ReviewRequest(target="https://github.com/owner/repo", mode="direct"),
            )

        self.assertEqual(context.exception.status_code, 401)

    @patch("repo_review_agent.web.SupabaseHistoryStore")
    @patch("repo_review_agent.web.get_supabase_user")
    def test_review_endpoint_saves_history_for_authenticated_user(
        self,
        mock_get_user,
        mock_store_class,
    ) -> None:
        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import ReviewRequest, create_app

        mock_get_user.return_value = AuthUser(id="user-id", email="user@example.com")
        mock_store = mock_store_class.from_env.return_value
        mock_store.save_report.return_value.to_dict.return_value = {
            "repository_id": "repo-id",
            "review_run_id": "run-id",
            "health_score": 95,
            "new_findings_count": 1,
            "existing_findings_count": 0,
            "resolved_findings_count": 0,
        }

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            endpoint = _route_endpoint(create_app(), "/review")

            with patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "true", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ):
                response = endpoint(
                    _fake_request(headers={"authorization": "Bearer access-token"}),
                    ReviewRequest(
                        target=str(root),
                        mode="direct",
                        save_history=True,
                        history_repo_url="owner/repo",
                    ),
                )

        self.assertEqual(response["history"]["review_run_id"], "run-id")
        mock_store.save_report.assert_called_once()
        self.assertEqual(mock_store.save_report.call_args.kwargs["owner_id"], "user-id")
        self.assertEqual(mock_store.save_report.call_args.kwargs["repo_url"], "owner/repo")

    @patch("repo_review_agent.web.execute_review_request")
    def test_review_job_endpoint_runs_review_in_background(self, mock_execute_review) -> None:
        from repo_review_agent.web import ReviewRequest, create_app

        mock_execute_review.return_value = {
            "markdown": "# Report",
            "report": {"repo_name": "repo", "findings": []},
        }

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            app = create_app()
            submit_endpoint = _route_endpoint(app, "/review/jobs")
            get_endpoint = _route_endpoint(app, "/review/jobs/{job_id}")

            with patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "true", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ):
                submitted = submit_endpoint(
                    _fake_request(headers={}),
                    ReviewRequest(target=str(root), mode="direct"),
                )
                completed = _wait_for_completed_job(get_endpoint, submitted["job_id"])

        self.assertIn(submitted["status"], {"queued", "running", "completed"})
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["markdown"], "# Report")
        mock_execute_review.assert_called_once()

    def test_review_job_endpoint_requires_login_before_saving_history(self) -> None:
        from fastapi import HTTPException

        from repo_review_agent.web import ReviewRequest, create_app

        endpoint = _route_endpoint(create_app(), "/review/jobs")

        with (
            patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "true", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ),
            self.assertRaises(HTTPException) as context,
        ):
            endpoint(
                _fake_request(headers={}),
                ReviewRequest(
                    target="https://github.com/owner/repo",
                    mode="direct",
                    save_history=True,
                ),
            )

        self.assertEqual(context.exception.status_code, 401)

    def test_review_job_endpoints_map_store_errors(self) -> None:
        from fastapi import HTTPException

        from repo_review_agent.history import HistoryStoreError
        from repo_review_agent.web import ReviewRequest, create_app

        class BrokenJobStore:
            def submit(self, *, request, user):  # type: ignore[no-untyped-def]
                raise HistoryStoreError("submit failed")

            def get(self, job_id):  # type: ignore[no-untyped-def]
                raise HistoryStoreError("get failed")

        with patch("repo_review_agent.web.build_review_job_store", return_value=BrokenJobStore()):
            app = create_app()
        submit_endpoint = _route_endpoint(app, "/review/jobs")
        get_endpoint = _route_endpoint(app, "/review/jobs/{job_id}")

        with (
            patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "true", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ),
            self.assertRaises(HTTPException) as submit_context,
        ):
            submit_endpoint(
                _fake_request(headers={}),
                ReviewRequest(target="https://github.com/owner/repo", mode="direct"),
            )

        with self.assertRaises(HTTPException) as get_context:
            get_endpoint(_fake_request(headers={}), "job-id")

        self.assertEqual(submit_context.exception.status_code, 400)
        self.assertEqual(get_context.exception.status_code, 400)

    def test_review_job_endpoint_returns_not_found_for_missing_jobs(self) -> None:
        from fastapi import HTTPException

        from repo_review_agent.web import create_app

        class EmptyJobStore:
            def get(self, job_id):  # type: ignore[no-untyped-def]
                return None

        with patch("repo_review_agent.web.build_review_job_store", return_value=EmptyJobStore()):
            get_endpoint = _route_endpoint(create_app(), "/review/jobs/{job_id}")

        with self.assertRaises(HTTPException) as context:
            get_endpoint(_fake_request(headers={}), "missing-job")

        self.assertEqual(context.exception.status_code, 404)

    @patch("repo_review_agent.web.execute_review_request")
    @patch("repo_review_agent.web.get_supabase_user")
    def test_review_job_endpoint_protects_user_owned_jobs(
        self,
        mock_get_user,
        mock_execute_review,
    ) -> None:
        from fastapi import HTTPException

        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import ReviewRequest, create_app

        mock_execute_review.return_value = {"markdown": "# Report", "report": {}}
        mock_get_user.return_value = AuthUser(id="owner-id", email="owner@example.com")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            app = create_app()
            submit_endpoint = _route_endpoint(app, "/review/jobs")
            get_endpoint = _route_endpoint(app, "/review/jobs/{job_id}")

            with patch.dict(
                "os.environ",
                {"REPO_REVIEW_ALLOW_LOCAL_TARGETS": "true", "REPO_REVIEW_API_TOKEN": ""},
                clear=False,
            ):
                submitted = submit_endpoint(
                    _fake_request(headers={"authorization": "Bearer owner-token"}),
                    ReviewRequest(target=str(root), mode="direct"),
                )
                mock_get_user.return_value = AuthUser(id="other-id", email="other@example.com")
                with self.assertRaises(HTTPException) as context:
                    get_endpoint(
                        _fake_request(headers={"authorization": "Bearer other-token"}),
                        submitted["job_id"],
                    )

        self.assertEqual(context.exception.status_code, 403)

    @patch("repo_review_agent.web.SupabaseHistoryStore")
    @patch("repo_review_agent.web.get_supabase_user")
    def test_history_api_returns_authenticated_repository_data(
        self,
        mock_get_user,
        mock_store_class,
    ) -> None:
        from repo_review_agent.auth import AuthUser
        from repo_review_agent.web import create_app

        mock_get_user.return_value = AuthUser(id="user-id", email="user@example.com")
        mock_store = mock_store_class.from_env.return_value
        mock_store.list_repositories.return_value = [{"id": "repo-id", "repo_name": "repo"}]
        mock_store.get_project_detail.return_value = {
            "repository": {"id": "repo-id", "repo_name": "repo"},
            "runs": [],
            "latestRun": None,
            "findings": [],
            "aiReview": None,
        }

        app = create_app()
        repositories_endpoint = _route_endpoint(app, "/history/repositories")
        detail_endpoint = _route_endpoint(app, "/history/repositories/{repository_id}")

        repositories = repositories_endpoint(_fake_request(headers={"authorization": "Bearer token"}))
        detail = detail_endpoint(_fake_request(headers={"authorization": "Bearer token"}), "repo-id")

        self.assertEqual(repositories["repositories"][0]["id"], "repo-id")
        self.assertEqual(detail["repository"]["id"], "repo-id")
        mock_store.list_repositories.assert_called_once_with(owner_id="user-id")
        mock_store.get_project_detail.assert_called_once_with(
            repository_id="repo-id",
            owner_id="user-id",
        )

    @patch("repo_review_agent.web.SupabaseHistoryStore")
    @patch("repo_review_agent.web.get_supabase_user")
    def test_history_api_maps_not_found_and_store_errors(
        self,
        mock_get_user,
        mock_store_class,
    ) -> None:
        from fastapi import HTTPException

        from repo_review_agent.auth import AuthUser
        from repo_review_agent.history import HistoryNotFoundError, HistoryStoreError
        from repo_review_agent.web import create_app

        mock_get_user.return_value = AuthUser(id="user-id", email="user@example.com")
        mock_store = mock_store_class.from_env.return_value
        app = create_app()
        repositories_endpoint = _route_endpoint(app, "/history/repositories")
        detail_endpoint = _route_endpoint(app, "/history/repositories/{repository_id}")

        mock_store.get_project_detail.side_effect = HistoryNotFoundError("missing")
        with self.assertRaises(HTTPException) as not_found_context:
            detail_endpoint(_fake_request(headers={"authorization": "Bearer token"}), "missing")

        mock_store.get_project_detail.side_effect = HistoryStoreError("offline")
        with self.assertRaises(HTTPException) as detail_error_context:
            detail_endpoint(_fake_request(headers={"authorization": "Bearer token"}), "repo-id")

        mock_store.list_repositories.side_effect = HistoryStoreError("offline")
        with self.assertRaises(HTTPException) as list_error_context:
            repositories_endpoint(_fake_request(headers={"authorization": "Bearer token"}))

        self.assertEqual(not_found_context.exception.status_code, 404)
        self.assertEqual(detail_error_context.exception.status_code, 400)
        self.assertEqual(list_error_context.exception.status_code, 400)

    def test_execute_review_request_requires_user_when_saving_history(self) -> None:
        from repo_review_agent.models import ReviewReport
        from repo_review_agent.web import ReviewRequest, execute_review_request

        with (
            patch("repo_review_agent.web.resolve_target") as mock_resolve_target,
            patch("repo_review_agent.web.run_review_for_path") as mock_run_review,
            self.assertRaises(PermissionError),
        ):
            mock_resolve_target.return_value.__enter__.return_value = Path(".")
            mock_run_review.return_value = ReviewReport(
                repo_name="repo",
                generated_at="2026-06-16T00:00:00+00:00",
                overview=[],
                metrics={},
                framework_signals={},
                findings=[],
            )
            execute_review_request(
                ReviewRequest(
                    target="https://github.com/owner/repo",
                    mode="direct",
                    save_history=True,
                ),
                None,
            )

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

        with (
            patch.dict("os.environ", {"PORT": "10000"}, clear=False),
            patch.object(web.uvicorn, "run") as mock_run,
        ):
            web.main()

        mock_run.assert_called_once_with(
            "repo_review_agent.web:create_app",
            factory=True,
            host="0.0.0.0",
            port=10000,
        )


def _fake_request(headers: dict[str, str]):
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host="127.0.0.1"))


class _ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)


class _FakeSupabaseJobStorage:
    def __init__(self, *, raise_on_failed_update: bool = False) -> None:
        self.raise_on_failed_update = raise_on_failed_update
        self.rows: dict[str, dict] = {}
        self.created_payload: dict | None = None
        self.updated_statuses: list[str] = []

    def create_job(
        self,
        *,
        target: str,
        request_payload: dict,
        owner_id: str | None = None,
    ) -> dict:
        self.created_payload = {
            "target": target,
            "request_json": request_payload,
            "owner_id": owner_id,
        }
        row = {
            "id": "job-id",
            "owner_id": owner_id,
            "status": "queued",
            "target": target,
            "request_json": request_payload,
            "result_json": None,
            "error": None,
            "created_at": "created",
            "updated_at": "updated",
        }
        self.rows[row["id"]] = row
        return dict(row)

    def get_job(self, job_id: str) -> dict | None:
        row = self.rows.get(job_id)
        return dict(row) if row else None

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> dict:
        self.updated_statuses.append(status)
        if status == "failed" and self.raise_on_failed_update:
            from repo_review_agent.history import HistoryStoreError

            raise HistoryStoreError("failed status write failed")

        row = self.rows.setdefault(
            job_id,
            {
                "id": job_id,
                "owner_id": None,
                "target": "https://github.com/owner/repo",
                "created_at": "created",
                "updated_at": "updated",
            },
        )
        row["status"] = status
        if result is not None:
            row["result_json"] = result
        if error is not None:
            row["error"] = error
        return dict(row)

    def fail_stale_running_jobs(self) -> int:
        return 2


def _route_endpoint(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


def _run_lifespan(app) -> None:
    import asyncio

    async def _drive() -> None:
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(_drive())


def _wait_for_completed_job(get_endpoint, job_id: str):
    for _ in range(50):
        job = get_endpoint(_fake_request(headers={}), job_id)
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            raise AssertionError(job.get("error"))
        time.sleep(0.02)
    raise AssertionError("Review job did not complete.")


if __name__ == "__main__":
    unittest.main()
