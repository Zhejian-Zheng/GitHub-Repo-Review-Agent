from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .auth import AuthError, AuthUser, bearer_token_from_headers, get_supabase_user
from .cli import resolve_target
from .env import load_local_env
from .history import (
    HistoryNotFoundError,
    HistoryStoreError,
    SupabaseHistoryStore,
    SupabaseReviewJobStore,
)
from .i18n import localize_report
from .job_runtime import run_isolated
from .llm import AIProviderError
from .report import render_markdown
from .security import (
    InMemoryRateLimiter,
    bool_from_env,
    client_identifier,
    int_from_env,
    request_token_matches,
    validate_target_policy,
)
from .service import run_review

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
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


class ReviewRequest(BaseModel):
    target: str = Field(..., description="Local repository path or GitHub URL.")
    mode: Literal["direct", "agent", "function-calling"] = "agent"
    ai_provider: Literal["none", "openai", "openrouter", "anthropic", "ollama"] = "none"
    ai_model: str | None = None
    report_language: Literal["en", "zh-CN"] = "en"
    max_files: int = Field(500, ge=1, le=WEB_MAX_FILES_LIMIT)
    max_file_size: int = Field(512_000, ge=1_024, le=WEB_MAX_FILE_SIZE_LIMIT)
    ai_token_budget: int = Field(20_000, ge=256, le=200_000)
    vulnerability_scan: bool = False
    lint: bool = False
    save_history: bool = False
    history_repo_url: str | None = None


class FindingFeedbackRequest(BaseModel):
    status: Literal["confirmed", "false_positive", "ignored"]
    reason: str = Field("", max_length=2000)
    expires_at: datetime | None = None


class ReportQuestionRequest(BaseModel):
    job_id: str | None = None
    report: dict[str, Any] | None = None
    question: str = Field(..., min_length=1, max_length=2000)
    provider: Literal["none", "openai", "openrouter", "anthropic", "ollama"] = "none"
    model: str | None = None
    language: Literal["en", "zh-CN"] = "en"
    token_budget: int = Field(4000, ge=256, le=20_000)


@dataclass
class ReviewJob:
    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    owner_id: str | None
    owner_email: str | None
    created_at: str
    updated_at: str
    target: str
    phase: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self, *, include_result: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "phase": self.phase,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "target": self.target,
        }
        if self.error:
            payload["error"] = self.error
        if include_result and self.result is not None:
            payload["result"] = self.result
        return payload


class JobCapacityError(RuntimeError):
    pass


class BaseReviewJobStore:
    durable_history = False

    def __init__(self, *, max_workers: int = WEB_JOB_WORKERS, max_pending: int | None = None,
                 per_user_limit: int | None = None, result_ttl: int | None = None,
                 daily_limit: int | None = None) -> None:
        self.max_workers = max_workers
        self.daily_limit = daily_limit if daily_limit is not None else int_from_env("REPO_REVIEW_DAILY_JOB_LIMIT", 100, minimum=1)
        self._worker_context = threading.local()
        self.max_pending = max_pending if max_pending is not None else int_from_env(
            "REPO_REVIEW_JOB_MAX_PENDING", 20, minimum=1)
        self.per_user_limit = per_user_limit if per_user_limit is not None else int_from_env(
            "REPO_REVIEW_JOB_PER_USER_LIMIT", 2, minimum=1)
        self.result_ttl = result_ttl if result_ttl is not None else int_from_env(
            "REPO_REVIEW_JOB_RESULT_TTL", 86400, minimum=1)
        self.timeout = int_from_env("REPO_REVIEW_JOB_TIMEOUT", 600, minimum=1)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="repo-review")
        self._stop = threading.Event()

    def shutdown(self) -> None:
        self._stop.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _dispatch(self, job_id: str, request: ReviewRequest, user: AuthUser | None) -> None:
        self._executor.submit(self._run, job_id, copy.deepcopy(request), copy.deepcopy(user))

    def _execute(self, request: ReviewRequest, user: AuthUser | None,
                 on_progress: Callable[[str], None] | None = None) -> dict:
        # The monitor runs on a different thread, so capture worker-local identity now.
        job_id = getattr(self._worker_context, "job_id", "")
        return run_isolated(_review_request_payload(request), user.to_dict() if user else None,
                            timeout=self.timeout, on_progress=on_progress, stop=self._stop,
                            defer_history=self.durable_history and request.save_history,
                            cancelled=lambda: self._is_cancelled(job_id))

    def execute_sync(self, request: ReviewRequest, user: AuthUser | None) -> dict:
        job = self.submit(request=request, user=user)
        while not self._stop.is_set():
            current = self.get(job.id)
            if current is None:
                raise RuntimeError("Review result expired.")
            if current.status == "completed":
                return current.result or {}
            if current.status == "cancelled":
                raise RuntimeError("Review cancelled.")
            if current.status == "failed":
                raise RuntimeError(current.error or "Review failed.")
            self._stop.wait(0.05)
        raise RuntimeError("Server is shutting down.")

    def _run(self, job_id: str, request: ReviewRequest, user: AuthUser | None) -> None:
        try:
            self._worker_context.job_id = job_id
            if self._is_cancelled(job_id):
                return
            self._set_running(job_id)
            result = self._execute(request, user, lambda phase: self._set_phase(job_id, phase))
            for attempt in range(3):
                try:
                    self._set_completed(job_id, result)
                    break
                except HistoryStoreError:
                    if attempt == 2 or self._stop.is_set():
                        raise
                    self._stop.wait(0.1 * (attempt + 1))
        except BaseException as exc:
            from .redaction import redact_text
            try:
                message = ("Review storage is unavailable. Try again later."
                           if isinstance(exc, HistoryStoreError) else redact_text(str(exc)))
                self._set_failed(job_id, message)
            except Exception:
                # Durable leases expire and are retried by the scheduler after DB recovery.
                logging.getLogger(__name__).error("Could not persist review failure; lease recovery will retry")

    def _is_cancelled(self, job_id: str) -> bool:
        job = self.get(job_id)
        return job is not None and job.status == "cancelled"

    def _set_phase(self, job_id: str, phase: str) -> None:  # pragma: no cover - abstract hook.
        raise NotImplementedError

    def _set_running(self, job_id: str) -> None:  # pragma: no cover - abstract hook.
        raise NotImplementedError

    def _set_completed(self, job_id: str, result: dict[str, Any]) -> None:  # pragma: no cover - abstract hook.
        raise NotImplementedError

    def _set_failed(self, job_id: str, error: str) -> None:  # pragma: no cover - abstract hook.
        raise NotImplementedError


class InMemoryReviewJobStore(BaseReviewJobStore):
    def __init__(self, *, max_workers: int = WEB_JOB_WORKERS, **kwargs) -> None:
        super().__init__(max_workers=max_workers, **kwargs)
        self._jobs: dict[str, ReviewJob] = {}
        self._lock = threading.Lock()
        self._daily_usage: dict[tuple[str, str | None], int] = {}
        self._cleaner: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._cleaner is None and not self._stop.is_set():
                self._cleaner = threading.Thread(target=self._cleanup_loop, daemon=True,
                                                 name="review-result-cleaner")
                self._cleaner.start()

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(min(60, max(1, self.result_ttl))):
            with self._lock:
                self._cleanup()

    def shutdown(self) -> None:
        super().shutdown()
        if self._cleaner:
            self._cleaner.join()


    def _cleanup(self) -> None:
        cutoff = time.time() - self.result_ttl
        self._jobs = {key: job for key, job in self._jobs.items()
                      if job.status in {"queued", "running"}
                      or datetime.fromisoformat(job.updated_at).timestamp() > cutoff}

    def submit(self, *, request: ReviewRequest, user: AuthUser | None) -> ReviewJob:
        now = _utc_now()
        job = ReviewJob(id=uuid.uuid4().hex, status="queued", owner_id=user.id if user else None,
                        owner_email=user.email if user else None, created_at=now, updated_at=now,
                        target=request.target)
        with self._lock:
            self._cleanup()
            active = [item for item in self._jobs.values() if item.status in {"queued", "running"}]
            if (self._stop.is_set() or len(active) >= self.max_pending
                    or sum(item.owner_id == job.owner_id for item in active) >= self.per_user_limit):
                raise JobCapacityError("Review queue or user quota reached. Try again later.")
            day = now[:10]
            self._daily_usage = {key: count for key, count in self._daily_usage.items() if key[0] == day}
            quota_key = (day, job.owner_id)
            if self._daily_usage.get(quota_key, 0) >= self.daily_limit:
                raise JobCapacityError("Daily review quota reached. Try again tomorrow (UTC).")
            self._daily_usage[quota_key] = self._daily_usage.get(quota_key, 0) + 1
            self._jobs[job.id] = job
        try:
            self._dispatch(job.id, request, user)
        except Exception:
            with self._lock:
                self._jobs.pop(job.id, None)
                self._daily_usage[quota_key] -= 1
            raise
        return copy.deepcopy(job)

    def admit_question(self, owner_id: str) -> None:
        with self._lock:
            day = _utc_now()[:10]
            self._daily_usage = {key: count for key, count in self._daily_usage.items() if key[0] == day}
            key = (day, owner_id)
            if self._daily_usage.get(key, 0) >= self.daily_limit:
                raise JobCapacityError("Daily review quota reached. Try again tomorrow (UTC).")
            self._daily_usage[key] = self._daily_usage.get(key, 0) + 1

    def get(self, job_id: str) -> ReviewJob | None:
        with self._lock:
            self._cleanup()
            return copy.deepcopy(self._jobs.get(job_id))

    def cancel(self, job_id: str, owner_id: str | None) -> ReviewJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if not owner_id or job.owner_id != owner_id:
                raise PermissionError("You do not have access to this review job.")
            if job.status in {"queued", "running"}:
                job.status = job.phase = "cancelled"
                job.updated_at = _utc_now()
                job.result = None
                job.error = None
            return copy.deepcopy(job)

    def _set_phase(self, job_id: str, phase: str) -> None:
        with self._lock:
            if job_id in self._jobs and self._jobs[job_id].status != "cancelled":
                self._jobs[job_id].phase = phase
                self._jobs[job_id].updated_at = _utc_now()

    def _set_running(self, job_id: str) -> None:
        self._update(job_id, status="running")

    def _set_completed(self, job_id: str, result: dict[str, Any]) -> None:
        self._update(job_id, status="completed", result=result)

    def _set_failed(self, job_id: str, error: str) -> None:
        self._update(job_id, status="failed", error=error)

    def _update(self, job_id: str, *, status: Literal["queued", "running", "completed", "failed", "cancelled"],
                result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status == "cancelled":
                return
            job.status = status
            job.phase = status if status != "running" else "cloning"
            job.updated_at = _utc_now()
            job.result = result
            job.error = error


class SupabaseBackedReviewJobStore(BaseReviewJobStore):
    durable_history = True

    def __init__(self, *, storage: SupabaseReviewJobStore | None = None,
                 max_workers: int = WEB_JOB_WORKERS, **kwargs) -> None:
        super().__init__(max_workers=max_workers, **kwargs)
        self._storage = storage or SupabaseReviewJobStore.from_env()
        self._leases: dict[str, str] = {}
        self._schedule_lock = threading.RLock()
        self._scheduler: threading.Thread | None = None

    def start(self) -> None:
        with self._schedule_lock:
            if self._scheduler is None and not self._stop.is_set():
                self._scheduler = threading.Thread(target=self._schedule_loop, daemon=True,
                                                   name="review-job-scheduler")
                self._scheduler.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._scheduler:
            self._scheduler.join()
        super().shutdown()

    def _schedule_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sweep()
            except Exception:
                logging.getLogger(__name__).error("Review queue sweep failed; retrying")
            self._stop.wait(2)

    def sweep(self) -> None:
        with self._schedule_lock:
            self._storage.recover_jobs(result_ttl=self.result_ttl)
            while len(self._leases) < self.max_workers and not self._stop.is_set():
                token = uuid.uuid4().hex
                row = self._storage.claim_job(lease_token=token, lease_seconds=self.timeout + 30)
                if row is None:
                    break
                job_id = str(row["id"])
                self._leases[job_id] = token
                try:
                    request = ReviewRequest(**row["request_json"])
                    user = AuthUser(id=row["owner_id"]) if row.get("owner_id") else None
                    self._dispatch(job_id, request, user)
                except Exception as exc:
                    try:
                        self._set_failed(job_id, str(exc))
                    finally:
                        self._leases.pop(job_id, None)

    def _run(self, job_id: str, request: ReviewRequest, user: AuthUser | None) -> None:
        try:
            super()._run(job_id, request, user)
        finally:
            with self._schedule_lock:
                self._leases.pop(job_id, None)

    def submit(self, *, request: ReviewRequest, user: AuthUser | None) -> ReviewJob:
        if self._stop.is_set():
            raise JobCapacityError("Server is shutting down.")
        row = self._storage.enqueue_job(target=request.target, request_payload=_review_request_payload(request),
                                        owner_id=user.id if user else None,
                                        max_pending=self.max_pending, per_user_limit=self.per_user_limit,
                                        daily_limit=self.daily_limit)
        if row is None:
            raise JobCapacityError("Review queue or user quota reached. Try again later.")
        self.start()
        return _job_from_supabase_row(row)

    def admit_question(self, owner_id: str) -> None:
        admitted = self._storage._request("POST", "rpc/admit_review_question",
                                         {"p_owner": owner_id, "p_daily_limit": self.daily_limit})
        if admitted is not True:
            raise JobCapacityError("Daily review quota reached. Try again tomorrow (UTC).")

    def get(self, job_id: str) -> ReviewJob | None:
        row = self._storage.get_job(job_id)
        return _job_from_supabase_row(row) if row else None

    def cancel(self, job_id: str, owner_id: str | None) -> ReviewJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        if not owner_id or job.owner_id != owner_id:
            raise PermissionError("You do not have access to this review job.")
        row = self._storage.request_cancel(job_id, owner_id=owner_id)
        return _job_from_supabase_row(row) if row else None

    def _set_running(self, job_id: str) -> None:
        # Claim RPC has already atomically set running and assigned the lease.
        pass

    def _set_phase(self, job_id: str, phase: str) -> None:
        self._storage.write_claimed_job(job_id, lease_token=self._leases[job_id], phase=phase)

    def _set_completed(self, job_id: str, result: dict[str, Any]) -> None:
        if "_pending_history" in result:
            self._storage.complete_with_history(job_id, lease_token=self._leases[job_id], result=result)
        else:
            self._storage.write_claimed_job(job_id, lease_token=self._leases[job_id], status="completed", result=result)

    def _set_failed(self, job_id: str, error: str) -> None:
        self._storage.write_claimed_job(job_id, lease_token=self._leases[job_id], status="failed", error=error)


def build_review_job_store() -> InMemoryReviewJobStore | SupabaseBackedReviewJobStore:
    mode = os.environ.get("REPO_REVIEW_JOB_STORE", "auto").strip().lower()
    if mode == "memory":
        return InMemoryReviewJobStore()
    if mode == "supabase":
        return SupabaseBackedReviewJobStore()
    if os.environ.get("SUPABASE_URL") and (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    ):
        return SupabaseBackedReviewJobStore()
    return InMemoryReviewJobStore()


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
                review_jobs.admit_question(user.id)
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


def execute_review_request(request: ReviewRequest, user: AuthUser | None,
                           on_progress: Callable[[str], None] | None = None, *,
                           defer_history: bool = False) -> dict:
    if on_progress:
        on_progress("cloning")
    with resolve_target(request.target) as repo_path:
        if on_progress:
            on_progress("analyzing")
        report = run_review_for_path(request, repo_path, **({"on_progress": on_progress} if on_progress else {}))

    history_result = None
    pending_history = None
    if request.save_history:
        if user is None:
            raise PermissionError("Sign in before saving review history.")
        arguments = dict(report=report, repo_url=request.history_repo_url or request.target,
                         report_markdown=render_markdown(report, language=request.report_language),
                         owner_id=user.id)
        if defer_history:
            from .persistence import history_payload
            pending_history = history_payload(**arguments)
        else:
            history_result = SupabaseHistoryStore.from_env().save_report(**arguments)

    if history_result:
        report = replace(report, finding_feedback=history_result.finding_feedback)
    report = localize_report(report, request.report_language)
    response = {
        "markdown": render_markdown(report, language=request.report_language),
        "report": report.to_dict(),
    }
    if pending_history is not None:
        response["_pending_history"] = pending_history
    if history_result:
        response["history"] = history_result.to_dict()
    return response


class AuthTokenCache:
    """Short-lived cache of verified Supabase tokens.

    Token verification is a network round-trip to Supabase on every request.
    Caching the resolved user for a short TTL removes that latency for bursts of
    requests from the same signed-in client. The trade-off is that a revoked
    token stays accepted until its cache entry expires, so keep the TTL small.
    """

    def __init__(self, *, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
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


def run_review_for_path(request: ReviewRequest, repo_path: Path, on_progress=None):
    return run_review(
        repo_path, mode=request.mode, max_files=request.max_files,
        max_file_size=request.max_file_size, ai_provider=request.ai_provider,
        ai_model=request.ai_model, report_language=request.report_language,
        run_linters=request.lint, ai_token_budget=request.ai_token_budget,
        vulnerability_scan=request.vulnerability_scan,
        **({"on_progress": on_progress} if on_progress else {}),
    )


def _review_request_payload(request: ReviewRequest) -> dict[str, Any]:
    if hasattr(request, "model_dump"):
        return request.model_dump()
    return request.dict()


def _job_from_supabase_row(row: dict[str, Any]) -> ReviewJob:
    status = str(row.get("status") or "")
    if status not in {"queued", "running", "completed", "failed", "cancelled"}:
        raise HistoryStoreError("Supabase review job row has an invalid status.")

    result = row.get("result_json")
    if result is not None and not isinstance(result, dict):
        raise HistoryStoreError("Supabase review job result_json must be an object.")

    if result and "history" in result and isinstance(result.get("report"), dict):
        from .persistence import restore_report
        result = {**result, "markdown": render_markdown(
            restore_report(result["report"]),
            language=(row.get("request_json") or {}).get("report_language", "en"))}

    return ReviewJob(
        id=str(row.get("id") or ""),
        status=status,
        owner_id=row.get("owner_id"),
        owner_email=None,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        target=str(row.get("target") or ""),
        result=result,
        phase=str(row.get("phase") or status),
        error=row.get("error"),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
