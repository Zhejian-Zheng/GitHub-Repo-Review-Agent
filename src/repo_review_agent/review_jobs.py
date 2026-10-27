"""Review scheduling, admission and durable job lifecycle; no HTTP imports."""
from __future__ import annotations

import copy
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .auth import AuthUser
from .history import HistoryStoreError, SupabaseReviewJobStore
from .job_runtime import run_isolated
from .question_runtime import QuestionCapacityError, QuestionRuntime
from .report import public_report_data, render_markdown
from .requests import ReviewRequest
from .security import int_from_env


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


JobCapacityError = QuestionCapacityError


class BaseReviewJobStore:
    durable_history = False

    def __init__(self, *, max_workers: int | None = None, max_pending: int | None = None,
                 per_user_limit: int | None = None, result_ttl: int | None = None,
                 daily_limit: int | None = None) -> None:
        self.max_workers = max_workers if max_workers is not None else int_from_env("REPO_REVIEW_JOB_WORKERS", 2, minimum=1)
        self.daily_limit = daily_limit if daily_limit is not None else int_from_env("REPO_REVIEW_DAILY_JOB_LIMIT", 100, minimum=1)
        self._worker_context = threading.local()
        self.max_pending = max_pending if max_pending is not None else int_from_env(
            "REPO_REVIEW_JOB_MAX_PENDING", 20, minimum=1)
        self.per_user_limit = per_user_limit if per_user_limit is not None else int_from_env(
            "REPO_REVIEW_JOB_PER_USER_LIMIT", 2, minimum=1)
        self.result_ttl = result_ttl if result_ttl is not None else int_from_env(
            "REPO_REVIEW_JOB_RESULT_TTL", 86400, minimum=1)
        self.timeout = int_from_env("REPO_REVIEW_JOB_TIMEOUT", 600, minimum=1)
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="repo-review")
        self._stop = threading.Event()
        self._questions = QuestionRuntime()

    @contextmanager
    def question_slot(self, owner_id: str):
        if self._stop.is_set():
            raise JobCapacityError("Server is shutting down.")
        storage = self._storage if self.durable_history else None
        with self._questions.slot(owner_id, storage=storage):
            yield

    def execute_question(self, request, owner_id: str, report: dict) -> dict:
        with self.question_slot(owner_id):
            self.admit_question(owner_id)
            return self._questions.execute(request, report, stop=self._stop)

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
    def __init__(self, *, max_workers: int | None = None, **kwargs) -> None:
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
                 max_workers: int | None = None, **kwargs) -> None:
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
                except Exception:
                    try:
                        # Pydantic validation text includes the original stored input.
                        self._set_failed(job_id, "Review job could not be started. Check the stored request and worker availability.")
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

    if result is not None:
        # Never return the internal history envelope or the full inventory list
        # through a job poll; both can be large and are not client data.
        result = {key: value for key, value in result.items() if key != "_pending_history"}
        request_payload = row.get("request_json")
        language = request_payload.get("report_language", "en") if isinstance(request_payload, dict) else "en"
        if "history" in result and isinstance(result.get("report"), dict):
            from .persistence import restore_report
            result = {**result, "markdown": render_markdown(
                restore_report(result["report"]), language=language)}
        if isinstance(result.get("report"), dict):
            result = {**result, "report": public_report_data(result["report"])}

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


