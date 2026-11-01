"""Repository acquisition shared by CLI and background application use cases."""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from .security import int_from_env


class resolve_target:
    def __init__(self, target: str) -> None:
        self.target = target
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if _looks_like_git_url(self.target):
            self._tmpdir = tempfile.TemporaryDirectory(prefix="repo-review-")
            clone_path = Path(self._tmpdir.name) / "repo"
            try:
                _run_monitored_clone(self.target, clone_path)
                _check_checkout_budget(clone_path)
            except BaseException:
                self._tmpdir.cleanup()
                self._tmpdir = None
                raise
            return clone_path

        path = Path(self.target).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise SystemExit(f"Target path does not exist or is not a directory: {path}")
        return path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


def _looks_like_git_url(target: str) -> bool:
    parsed = urlparse(target)
    return parsed.scheme in {"http", "https", "ssh", "git"} or target.startswith("git@")


def _run_monitored_clone(target: str, clone_path: Path) -> None:
    timeout = max(1, int(os.environ.get("REPO_REVIEW_CLONE_TIMEOUT", "120")))
    command = ["git", "-c", "credential.helper=", "clone", "--depth", "1", "--",
               target, str(clone_path)]
    # Git accepts an empty destination; create it before the first size probe.
    clone_path.mkdir()
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
        env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
                 GIT_SSH_COMMAND="ssh -oBatchMode=yes -oConnectTimeout=15"),
    )
    try:
        while proc.poll() is None:
            _check_checkout_budget(clone_path, cloning=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                proc.wait(timeout=min(0.2, remaining))
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, command)
    except BaseException:
        # Stop writers before __enter__ removes the partially populated tree.
        if os.name == "posix":
            try:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
            except PermissionError:
                # macOS may report EPERM when the last group member just exited.
                if proc.poll() is None:
                    raise
        else:  # pragma: no cover - Windows process-tree termination.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=True, timeout=10,
            )
        proc.wait()
        raise


def _check_checkout_budget(root: Path, *, cloning: bool = False) -> None:
    """Include Git objects and links themselves, never their external targets.

    Used both during and after cloning. Only the live scan tolerates entries
    disappearing as Git renames/unlinks temporary objects and lock files.
    """
    byte_limit = int_from_env("REPO_REVIEW_CLONE_MAX_BYTES", 512_000_000, minimum=1)
    entry_limit = int_from_env("REPO_REVIEW_MAX_WALK_ENTRIES", 50_000, minimum=1)
    pending = [root]
    total_bytes = 0
    entries = 0
    try:
        while pending:
            try:
                stream = os.scandir(pending.pop())
            except FileNotFoundError:
                if cloning:
                    continue
                raise
            with stream:
                for entry in stream:
                    entries += 1
                    if entries > entry_limit:
                        raise RuntimeError("Repository acquisition budget exceeded.")
                    try:
                        total_bytes += entry.stat(follow_symlinks=False).st_size
                    except FileNotFoundError:
                        if cloning:
                            continue
                        raise
                    if total_bytes >= byte_limit:
                        raise RuntimeError("Repository acquisition budget exceeded.")
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
    except OSError as exc:
        raise RuntimeError("Repository acquisition budget could not be verified.") from exc
