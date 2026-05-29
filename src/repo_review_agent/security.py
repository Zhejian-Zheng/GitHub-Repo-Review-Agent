from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from threading import Lock
from urllib.parse import urlparse


TRUTHY_VALUES = {"1", "true", "yes", "on"}
FALSY_VALUES = {"0", "false", "no", "off"}


def bool_from_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSY_VALUES:
        return False
    return default


def int_from_env(name: str, default: int, *, minimum: int | None = None) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    if minimum is not None:
        return max(minimum, value)
    return value


def is_github_https_url(target: str) -> bool:
    parsed = urlparse(target.strip())
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.netloc.lower()
    if host not in {"github.com", "www.github.com"}:
        return False

    path_parts = [part for part in parsed.path.split("/") if part]
    return len(path_parts) >= 2


def validate_target_policy(target: str, *, allow_local_targets: bool | None = None) -> None:
    if allow_local_targets is None:
        allow_local_targets = bool_from_env("REPO_REVIEW_ALLOW_LOCAL_TARGETS", True)

    if allow_local_targets or is_github_https_url(target):
        return

    raise ValueError(
        "Public demo mode only allows GitHub repository URLs such as "
        "https://github.com/owner/repo."
    )


def request_token_matches(headers, expected_token: str | None) -> bool:
    if not expected_token:
        return True

    bearer_prefix = "Bearer "
    authorization = headers.get("authorization", "")
    if authorization.startswith(bearer_prefix):
        token = authorization[len(bearer_prefix) :]
        return hmac.compare_digest(token, expected_token)

    header_token = headers.get("x-repo-review-token", "")
    return hmac.compare_digest(header_token, expected_token)


def client_identifier(headers, fallback_host: str | None) -> str:
    forwarded_for = headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    return fallback_host or "unknown"


class InMemoryRateLimiter:
    def __init__(self, *, limit_per_minute: int, window_seconds: int = 60) -> None:
        self.limit_per_minute = max(0, limit_per_minute)
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        if self.limit_per_minute <= 0:
            return True

        current_time = time.time() if now is None else now
        earliest_allowed = current_time - self.window_seconds

        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= earliest_allowed:
                hits.popleft()

            if len(hits) >= self.limit_per_minute:
                return False

            hits.append(current_time)
            return True
