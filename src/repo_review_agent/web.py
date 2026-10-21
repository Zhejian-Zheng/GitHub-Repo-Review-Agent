from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from .application import execute_review_request as execute_review_request
from .application import run_review_for_path as run_review_for_path
from .auth import AuthError, AuthUser, bearer_token_from_headers, get_supabase_user
from .env import load_local_env
from .history import (
    HistoryNotFoundError,
    HistoryStoreError,
    SupabaseHistoryStore,
)
from .llm import AIProviderError
from .requests import FindingFeedbackRequest as FindingFeedbackRequest
from .requests import ReportQuestionRequest as ReportQuestionRequest
from .requests import ReviewRequest as ReviewRequest
from .review_jobs import BaseReviewJobStore as BaseReviewJobStore
from .review_jobs import InMemoryReviewJobStore as InMemoryReviewJobStore
from .review_jobs import JobCapacityError as JobCapacityError
from .review_jobs import ReviewJob as ReviewJob
from .review_jobs import SupabaseBackedReviewJobStore as SupabaseBackedReviewJobStore
from .review_jobs import _job_from_supabase_row as _job_from_supabase_row
from .review_jobs import _review_request_payload as _review_request_payload
from .review_jobs import _utc_now as _utc_now
from .review_jobs import build_review_job_store as build_review_job_store
from .security import (
    InMemoryRateLimiter,
    bool_from_env,
    client_identifier,
    int_from_env,
    request_token_matches,
    validate_target_policy,
)

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover - optional dependency guard.
    raise RuntimeError(
        "Web dependencies are not installed. Run `python -m pip install -e .[web]`."
    ) from exc

# Load .env before reading the module-level configuration constants below.
load_local_env()


FRONTEND_DIST = Path(
    os.environ.get(
        "REPO_REVIEW_FRONTEND_DIST",
        Path.cwd() / "frontend" / "dist",
    )
)
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"
WEB_MAX_FILES_LIMIT = int_from_env("REPO_REVIEW_MAX_FILES_LIMIT", 1_000, minimum=1)
WEB_MAX_FILE_SIZE_LIMIT = int_from_env(
    "REPO_REVIEW_MAX_FILE_SIZE_LIMIT",
    1_000_000,
    minimum=1_024,
)
WEB_RATE_LIMITER = InMemoryRateLimiter(
    limit_per_minute=int_from_env("REPO_REVIEW_RATE_LIMIT_PER_MINUTE", 30, minimum=0)
)
WEB_JOB_WORKERS = int_from_env("REPO_REVIEW_JOB_WORKERS", 2, minimum=1)
WEB_AUTH_CACHE_TTL = int_from_env("REPO_REVIEW_AUTH_CACHE_TTL", 60, minimum=0)

FALLBACK_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GitHub Repo Review Agent</title>
</head>
<body>
  <main style="font-family: system-ui, sans-serif; max-width: 720px; margin: 48px auto; line-height: 1.5;">
    <h1>GitHub Repo Review Agent</h1>
    <p>The React frontend has not been built yet.</p>
    <pre>cd frontend
npm install
npm run build
cd ..
repo-review-web</pre>
  </main>
</body>
</html>"""


def create_app() -> FastAPI:
    review_jobs = build_review_job_store()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        fail_stale = getattr(review_jobs, "fail_stale_running_jobs", None)
        if fail_stale:
            with suppress(HistoryStoreError):
                fail_stale()
        start = getattr(review_jobs, "start", None)
        if start:
            start()
        try:
            yield
        finally:
            shutdown = getattr(review_jobs, "shutdown", None)
            if shutdown:
                shutdown()

    app = FastAPI(title="GitHub Repo Review Agent", version="0.1.0", lifespan=lifespan)
    configure_cors(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/auth/me")
    def auth_me(http_request: Request) -> dict:
        user = authenticated_user_from_request(http_request, required=True)
        return {"user": user.to_dict()}

    @app.post("/review")
    def review_repository(http_request: Request, request: ReviewRequest) -> dict:
        user = authenticated_user_from_request(http_request)
        enforce_public_api_controls(http_request, request.target)

        if request.save_history and user is None:
            raise HTTPException(status_code=401, detail="Sign in before saving review history.")
        try:
            return review_jobs.execute_sync(request, user)
        except JobCapacityError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except (AIProviderError, RuntimeError, SystemExit, HistoryStoreError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/review/jobs")
    def submit_review_job(http_request: Request, request: ReviewRequest) -> dict:
        user = authenticated_user_from_request(http_request)
        enforce_public_api_controls(http_request, request.target)
        if request.save_history and user is None:
            raise HTTPException(status_code=401, detail="Sign in before saving review history.")
        try:
            job = review_jobs.submit(request=request, user=user)
        except JobCapacityError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except HistoryStoreError as exc:
            raise HTTPException(status_code=503, detail="Review storage is unavailable. Try again later.") from exc
        return job.to_dict(include_result=False)

    @app.get("/review/jobs/{job_id}")
    def get_review_job(http_request: Request, job_id: str) -> dict:
        user = authenticated_user_from_request(http_request)
        try:
            job = review_jobs.get(job_id)
        except HistoryStoreError as exc:
            raise HTTPException(status_code=503, detail="Review storage is unavailable. Try again later.") from exc
        if job is None:
            raise HTTPException(status_code=404, detail="Review job was not found.")
        if job.owner_id and (user is None or user.id != job.owner_id):
            raise HTTPException(status_code=403, detail="You do not have access to this review job.")
        return job.to_dict()

    @app.post("/review/jobs/{job_id}/cancel")
    def cancel_review_job(http_request: Request, job_id: str) -> dict:
        user = authenticated_user_from_request(http_request, required=True)
        try:
            job = review_jobs.cancel(job_id, user.id)
            if job is None:
                raise HTTPException(status_code=404, detail="Review job was not found.")
            return job.to_dict()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except HistoryStoreError as exc:
            raise HTTPException(status_code=503, detail="Review storage is unavailable. Try again later.") from exc

    @app.post("/review/questions")
    def report_question(http_request: Request, request: ReportQuestionRequest) -> dict:
        user = authenticated_user_from_request(http_request, required=request.provider != "none")
        if not request.question.strip():
            raise HTTPException(status_code=422, detail="Enter a question.")
        if not request_token_matches(http_request.headers, os.environ.get("REPO_REVIEW_API_TOKEN")):
            raise HTTPException(status_code=401, detail="Invalid or missing API token.")
        try:
            report = request.report
            if request.job_id:
                job = review_jobs.get(request.job_id)
                if job is None:
                    raise HTTPException(status_code=404, detail="Review job was not found.")
                if job.owner_id and (not user or user.id != job.owner_id):
                    raise HTTPException(status_code=403, detail="You do not have access to this review job.")
                if job.status != "completed":
                    raise HTTPException(status_code=409, detail="Wait for the report to finish.")
                report = (job.result or {}).get("report")
            if not report or len(json.dumps(report).encode("utf-8")) > 200_000:
                raise HTTPException(status_code=422, detail="Provide a completed report under 200 KB.")
            if request.provider != "none":
                return review_jobs.execute_question(request, user.id, report)
            from .questions import answer_report_question
            return answer_report_question(report, request.question, provider=request.provider,
                                          model=request.model, language=request.language,
                                          token_budget=request.token_budget)
        except JobCapacityError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except HistoryStoreError as exc:
            raise HTTPException(status_code=503, detail="Review storage is unavailable. Try again later.") from exc
        except (AIProviderError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            code = 504 if "deadline" in str(exc) else 400
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.post("/history/repositories/{repository_id}/findings/{fingerprint}/feedback")
    def finding_feedback(http_request: Request, repository_id: str, fingerprint: str,
                         request: FindingFeedbackRequest) -> dict:
        user = authenticated_user_from_request(http_request, required=True)
        try:
            return SupabaseHistoryStore.from_env().set_finding_feedback(
                repository_id=repository_id, fingerprint=fingerprint, owner_id=user.id,
                status=request.status, reason=request.reason,
                expires_at=request.expires_at.isoformat() if request.expires_at else None)
        except HistoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HistoryStoreError as exc:
            raise HTTPException(status_code=503, detail="Review storage is unavailable. Try again later.") from exc

    @app.get("/history/repositories")
    def history_repositories(http_request: Request) -> dict:
        user = authenticated_user_from_request(http_request, required=True)
        try:
            repositories = SupabaseHistoryStore.from_env().list_repositories(owner_id=user.id)
        except HistoryStoreError as exc:
            raise HTTPException(status_code=503, detail="Review storage is unavailable. Try again later.") from exc
        return {"repositories": repositories}

    @app.get("/history/repositories/{repository_id}")
    def history_project_detail(http_request: Request, repository_id: str) -> dict:
        user = authenticated_user_from_request(http_request, required=True)
        try:
            return SupabaseHistoryStore.from_env().get_project_detail(
                repository_id=repository_id,
                owner_id=user.id,
            )
        except HistoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HistoryStoreError as exc:
            raise HTTPException(status_code=503, detail="Review storage is unavailable. Try again later.") from exc

    if FRONTEND_ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS)), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        if FRONTEND_INDEX.exists():
            return FileResponse(FRONTEND_INDEX)
        return HTMLResponse(FALLBACK_HTML)

    return app


class AuthTokenCache:
    """Short-lived cache of verified Supabase tokens.

    Token verification is a network round-trip to Supabase on every request.
    Caching the resolved user for a short TTL removes that latency for bursts of
    requests from the same signed-in client. The trade-off is that a revoked
    token stays accepted until its cache entry expires, so keep the TTL small.
    """

    def __init__(self, *, ttl_seconds: int, max_entries: int = 4096) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max(1, max_entries)
        self._entries: dict[str, tuple[float, AuthUser]] = {}
        self._lock = threading.Lock()

    def get(self, token: str, *, now: float | None = None) -> AuthUser | None:
        if self.ttl_seconds <= 0:
            return None
        current_time = time.time() if now is None else now
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            expires_at, user = entry
            if expires_at <= current_time:
                del self._entries[token]
                return None
            return user

    def set(self, token: str, user: AuthUser, *, now: float | None = None) -> None:
        if self.ttl_seconds <= 0:
            return
        current_time = time.time() if now is None else now
        with self._lock:
            expired = [key for key, (expiry, _) in self._entries.items() if expiry <= current_time]
            for key in expired:
                del self._entries[key]
            self._entries.pop(token, None)
            while len(self._entries) >= self.max_entries:
                del self._entries[next(iter(self._entries))]
            self._entries[token] = (current_time + self.ttl_seconds, user)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


WEB_AUTH_CACHE = AuthTokenCache(ttl_seconds=WEB_AUTH_CACHE_TTL)


def authenticated_user_from_request(http_request: Request, *, required: bool | None = None) -> AuthUser | None:
    if required is None:
        required = bool_from_env("REPO_REVIEW_REQUIRE_AUTH", False)

    token = bearer_token_from_headers(http_request.headers)
    if not token:
        if required:
            raise HTTPException(status_code=401, detail="Sign in is required.")
        return None

    cached_user = WEB_AUTH_CACHE.get(token)
    if cached_user is not None:
        return cached_user

    try:
        user = get_supabase_user(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    WEB_AUTH_CACHE.set(token, user)
    return user


def enforce_public_api_controls(http_request: Request, target: str) -> None:
    expected_token = os.environ.get("REPO_REVIEW_API_TOKEN")
    if not request_token_matches(http_request.headers, expected_token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")

    client_id = client_identifier(
        http_request.headers,
        http_request.client.host if http_request.client else None,
        trust_forwarded=bool_from_env("REPO_REVIEW_TRUST_FORWARDED_FOR", True),
    )
    if not WEB_RATE_LIMITER.allow(client_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    try:
        validate_target_policy(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def configure_cors(app: FastAPI) -> None:
    origins = _csv_env("REPO_REVIEW_CORS_ORIGINS")
    if not origins:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Repo-Review-Token"],
    )


def _csv_env(name: str) -> list[str]:
    raw_value = os.environ.get(name, "")
    return [value.strip().rstrip("/") for value in raw_value.split(",") if value.strip()]


def main() -> None:
    uvicorn.run(
        "repo_review_agent.web:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )


app = create_app()
