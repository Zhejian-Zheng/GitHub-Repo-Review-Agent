"""Opt-in Langfuse v4 tracing with content suppression and bounded cleanup."""

from __future__ import annotations

import atexit
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from threading import Lock, Thread
from typing import Any
from urllib.parse import urlsplit

from langchain_core.callbacks import BaseCallbackHandler

_OMITTED = "[CONTENT OMITTED]"
_STATE = None
_STATE_KEY = None
_INIT_LOCK = Lock()


def mask_payload(*, data: Any, **kwargs: Any) -> str | None:
    """Suppress entire payloads: regex redaction cannot protect arbitrary code."""
    return None if data is None else _OMITTED


def mask_spans(*, params):
    """Allow operational attributes only; SDK masking alone misses status/params."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    keep = {
        "langfuse.observation.type",
        "langfuse.observation.level",
        "langfuse.observation.usage_details",
        "langfuse.observation.cost_details",
        "langfuse.observation.completion_start_time",
        "langfuse.observation.model.name",
    }
    return MaskOtelSpansResult(
        span_patches={
            identifier: OtelSpanPatch(
                delete_attributes=tuple(key for key in span.attributes if key not in keep)
            )
            for identifier, span in params.spans.items()
        }
    )


class _SafeCallback(BaseCallbackHandler):
    """Isolate telemetry faults and omit exception text before SDK status capture."""

    run_inline = True
    raise_error = False

    def __init__(self, delegate):
        self._delegate = delegate

    def __getattribute__(self, name):
        if name.startswith("on_"):
            delegate = object.__getattribute__(self, "_delegate")

            def forward(*args, **kwargs):
                with suppress(Exception):
                    method = getattr(delegate, name, None)
                    if method is None:
                        return None
                    if name.endswith("_error"):
                        args = tuple(
                            RuntimeError("Review operation failed")
                            if isinstance(arg, BaseException)
                            else arg
                            for arg in args
                        )
                        if "error" in kwargs:
                            kwargs["error"] = RuntimeError("Review operation failed")
                    return method(*args, **kwargs)
                return None

            return forward
        return object.__getattribute__(self, name)


@dataclass
class _State:
    client: Any
    handler_factory: Any
    flush_lock: Lock = field(default_factory=Lock)


def _flush_bounded(state: _State, timeout: float = 2.0, *, shutdown: bool = False) -> None:
    # A broken exporter must not accumulate background flush threads per review.
    if not state.flush_lock.acquire(blocking=False):
        return

    def finish():
        try:
            with suppress(Exception):
                if shutdown:
                    state.client.shutdown()
                else:
                    state.client.flush()
        finally:
            state.flush_lock.release()

    worker = Thread(target=finish, name="repo-review-telemetry-flush", daemon=True)
    try:
        worker.start()
    except Exception:
        state.flush_lock.release()
        return
    worker.join(timeout=max(0.0, min(timeout, 5.0)))


def _initialize(public_key: str, secret_key: str, base_url: str) -> _State:
    global _STATE, _STATE_KEY
    with _INIT_LOCK:
        key = (public_key, secret_key, base_url)
        if _STATE is not None:
            if key != _STATE_KEY:
                raise ValueError("Restart the process to change tracing configuration.")
            return _STATE

        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        # Keep other application/instrumentation spans out of this exporter.
        provider = TracerProvider(
            resource=Resource({"service.name": "repo-review-agent"}),
            shutdown_on_exit=False,
        )
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            timeout=2,
            debug=False,
            mask=mask_payload,
            mask_otel_spans=mask_spans,
            tracer_provider=provider,
            should_export_span=lambda span: (
                span.instrumentation_scope is not None
                and span.instrumentation_scope.name == "langfuse-sdk"
                and not span.events
            ),
        )
        # Langfuse clients are keyed globally by public key. Fail closed if another
        # integration initialized that key with a different privacy policy.
        if client._mask is not mask_payload:
            provider.shutdown()
            raise ValueError("A different Langfuse client owns this project key.")
        state = _State(client, lambda: _SafeCallback(CallbackHandler(public_key=public_key)))
        # SDK v4's registered ResourceManager.shutdown calls unbounded queue.join.
        # Own its exit hook so short-lived review workers cannot hang on telemetry.
        # This narrow compatibility boundary is covered against the real SDK.
        atexit.unregister(client._resources.shutdown)
        atexit.register(_flush_bounded, state, 2.0, shutdown=True)
        _STATE, _STATE_KEY = state, key
        return state


@contextmanager
def review_tracing() -> Iterator[dict[str, Any]]:
    """Yield per-invocation LangChain config; never suppress review exceptions.

    Tracing is disabled unless explicitly enabled with both credentials and a
    destination. No repository identity or source content is attached.
    """
    state = None
    observation = None
    config = {}
    if os.getenv("REPO_REVIEW_LANGFUSE_ENABLED", "").strip().lower() in {"true", "1", "yes"}:
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        base_url = os.getenv("LANGFUSE_BASE_URL", "").strip()
        try:
            destination = urlsplit(base_url)
            if (
                public_key
                and secret_key
                and destination.scheme in {"http", "https"}
                and destination.hostname
                and not destination.username
                and not destination.password
            ):
                state = _initialize(public_key, secret_key, base_url)
                config = {"callbacks": [state.handler_factory()], "run_name": "repository-review"}
                observation = state.client.start_as_current_observation(name="repository-review")
                observation.__enter__()
        except Exception:
            # Missing SDK, invalid config and tracing failures never prevent review.
            state = None
            observation = None
            config = {}
    try:
        yield config
    finally:
        if observation is not None:
            # Do not pass review exceptions to OTel's automatic exception recorder:
            # exception messages/stack traces can contain private repository content.
            with suppress(Exception):
                observation.__exit__(None, None, None)
        if state is not None:
            with suppress(Exception):
                _flush_bounded(state)


def record_evaluation_scores(scores: dict) -> bool:
    """Queue aggregate numeric scores for the active trace; omit dataset content."""
    import math
    if _STATE is None:
        return False
    with suppress(Exception):
        trace_id = _STATE.client.get_current_trace_id()
        if not trace_id:
            return False
        for name in ('recall', 'precision', 'forbidden_pass', 'citation_validity', 'ai_success', 'latency_seconds'):
            value = scores.get(name)
            if isinstance(value, (float, int)) and math.isfinite(value) and value >= 0:
                _STATE.client.create_score(trace_id=trace_id, name=name, value=float(value), data_type='NUMERIC')
        return True
    return False
