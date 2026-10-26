"""Question admission and killable execution, separate from HTTP request threads."""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter, defaultdict, deque
from contextlib import contextmanager

from .history import HistoryStoreError
from .job_runtime import run_isolated
from .security import int_from_env


class QuestionCapacityError(RuntimeError):
    pass


class QuestionRuntime:
    def __init__(self):
        self.limit = int_from_env("REPO_REVIEW_QUESTION_WORKERS", 2, minimum=1)
        self.per_user = int_from_env("REPO_REVIEW_QUESTION_PER_USER_LIMIT", 1, minimum=1)
        self.rate = int_from_env("REPO_REVIEW_QUESTION_RATE_PER_MINUTE", 10, minimum=1)
        self.timeout = int_from_env("REPO_REVIEW_QUESTION_TIMEOUT", 45, minimum=1)
        self._active = Counter()
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    @contextmanager
    def slot(self, owner, *, storage=None):
        if storage is not None:
            lease = storage._request("POST", "rpc/acquire_review_question", {
                "p_owner": owner, "p_global_limit": self.limit,
                "p_user_limit": self.per_user, "p_rate_limit": self.rate,
                "p_lease_seconds": self.timeout + 30,
            })
            if not isinstance(lease, str) or not lease:
                raise QuestionCapacityError("Question capacity or rate limit reached. Try again later.")
            try:
                yield
            finally:
                try:
                    storage._request("POST", "rpc/release_review_question", {"p_lease": lease})
                except HistoryStoreError:
                    # A crashed server or unavailable database cannot retain capacity forever.
                    logging.getLogger(__name__).warning("Question lease release failed; expiry will recover it")
            return
        with self._lock:
            now = time.monotonic()
            for key in list(self._hits):
                while self._hits[key] and self._hits[key][0] <= now - 60:
                    self._hits[key].popleft()
                if not self._hits[key]:
                    del self._hits[key]
            if (sum(self._active.values()) >= self.limit
                    or self._active[owner] >= self.per_user
                    or len(self._hits.get(owner, ())) >= self.rate):
                raise QuestionCapacityError("Question capacity or rate limit reached. Try again later.")
            self._active[owner] += 1
            self._hits[owner].append(now)
        try:
            yield
        finally:
            with self._lock:
                self._active[owner] -= 1
                if not self._active[owner]:
                    del self._active[owner]

    def execute(self, request, report, *, stop):
        return run_isolated(
            {**request.model_dump(), "report": report}, None,
            timeout=self.timeout, stop=stop, operation="question",
        )
