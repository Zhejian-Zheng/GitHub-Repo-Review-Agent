"""Killable review isolation; the parent owns and cleans all temporary files."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path


def run_isolated(request: dict, user: dict | None, *, timeout: float,
                 on_progress: Callable[[str], None] | None = None,
                 stop: threading.Event | None = None, defer_history: bool = False, cancelled: Callable[[], bool] | None = None, command: list[str] | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="repo-review-job-") as workspace:
        root = Path(workspace)
        (root / "input.json").write_text(json.dumps({"request": request, "user": user, "defer_history": defer_history}), encoding="utf-8")
        env = dict(os.environ, TMPDIR=workspace, TEMP=workspace, TMP=workspace)
        # No pipes: a verbose child cannot deadlock the supervisor or exhaust memory.
        proc = subprocess.Popen(command or [sys.executable, "-m", "repo_review_agent.job_runtime", workspace, str(timeout)],
                                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + timeout
        group_terminated = False

        def kill_group() -> None:
            nonlocal group_terminated
            if group_terminated:
                return
            if os.name == "posix":
                try:
                    with suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                except PermissionError:
                    # macOS can report EPERM for a group whose last process
                    # has just exited. Never hide a failure to kill a live child.
                    if proc.poll() is None:
                        raise
            elif proc.poll() is None:  # pragma: no cover - Windows fallback.
                proc.kill()
            # Watchdog and cleanup run sequentially (join below). Avoid sending
            # a second signal to an exited or potentially reused process group.
            group_terminated = True

        # The watchdog remains effective even if persisting progress is blocked
        # by a database outage. One watchdog exists per bounded active worker.
        watchdog = threading.Timer(timeout, kill_group)
        watchdog.daemon = True
        watchdog.start()
        seen = 0
        cancellation_seen = threading.Event()
        monitor_done = threading.Event()

        def watch_cancellation() -> None:
            while not monitor_done.wait(0.2):
                try:
                    if cancelled and cancelled():
                        cancellation_seen.set()
                        kill_group()
                        return
                except Exception:
                    # Transient storage failures do not turn into cancellation.
                    continue

        monitor = threading.Thread(target=watch_cancellation, daemon=True)
        monitor.start()

        def read_progress() -> None:
            nonlocal seen
            progress = root / "progress"
            if progress.exists():
                lines = progress.read_text(encoding="utf-8").splitlines()
                for phase in lines[seen:]:
                    if phase and on_progress:
                        on_progress(phase)
                seen = len(lines)

        try:
            while proc.poll() is None:
                if cancellation_seen.is_set():
                    raise RuntimeError("Review cancelled.")
                if stop is not None and stop.is_set():
                    raise RuntimeError("Review stopped during server shutdown.")
                if time.monotonic() >= deadline:
                    raise RuntimeError("Review exceeded its total execution deadline.")
                read_progress()
                time.sleep(0.05)
            if cancellation_seen.is_set() or (cancelled and cancelled()):
                raise RuntimeError("Review cancelled.")
            if time.monotonic() >= deadline:
                raise RuntimeError("Review exceeded its total execution deadline.")
            read_progress()
            output = root / "output.json"
            if not output.exists():
                raise RuntimeError("Review worker exited without a result.")
            result = json.loads(output.read_text(encoding="utf-8"))
            if "error" in result:
                raise RuntimeError(result["error"])
            return result["result"]
        finally:
            monitor_done.set()
            monitor.join(timeout=1)
            watchdog.cancel()
            watchdog.join()
            # Kill the entire group, including git/linters surviving the child.
            kill_group()
            proc.wait()


def main(workspace: str) -> None:
    from .auth import AuthUser
    from .web import ReviewRequest, execute_review_request

    root = Path(workspace)
    payload = json.loads((root / "input.json").read_text(encoding="utf-8"))

    def progress(phase: str) -> None:
        with (root / "progress").open("a", encoding="utf-8") as stream:
            stream.write(phase + "\n")

    try:
        user = AuthUser(**payload["user"]) if payload["user"] else None
        result = execute_review_request(ReviewRequest(**payload["request"]), user, on_progress=progress,
                                        **({"defer_history": True} if payload.get("defer_history") else {}))
        output = {"result": result}
    except BaseException as exc:
        from .redaction import redact_text
        output = {"error": redact_text(str(exc))}
    (root / "output.json").write_text(json.dumps(output), encoding="utf-8")


if __name__ == "__main__":
    # An orphaned child still dies on schedule if its web supervisor crashes.
    if os.name == "posix":
        def expire(signum, frame):
            os.killpg(os.getpgrp(), signal.SIGKILL)
        signal.signal(signal.SIGALRM, expire)
        signal.setitimer(signal.ITIMER_REAL, float(sys.argv[2]))
    main(sys.argv[1])
