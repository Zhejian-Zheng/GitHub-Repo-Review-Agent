"""Repository acquisition shared by CLI and background application use cases."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse


class resolve_target:
    def __init__(self, target: str) -> None:
        self.target = target
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if _looks_like_git_url(self.target):
            self._tmpdir = tempfile.TemporaryDirectory(prefix="repo-review-")
            clone_path = Path(self._tmpdir.name) / "repo"
            try:
                subprocess.run(
                    ["git", "-c", "credential.helper=", "clone", "--depth", "1", "--",
                     self.target, str(clone_path)],
                    check=True, capture_output=True, text=True,
                    timeout=max(1, int(os.environ.get("REPO_REVIEW_CLONE_TIMEOUT", "120"))),
                    stdin=subprocess.DEVNULL,
                    env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
                             GIT_SSH_COMMAND="ssh -oBatchMode=yes -oConnectTimeout=15"),
                )
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


