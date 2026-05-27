from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .analyzer import analyze_repository
from .report import render_markdown, write_json, write_markdown


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    with resolve_target(args.target) as repo_path:
        report = analyze_repository(
            repo_path,
            max_files=args.max_files,
            max_file_size=args.max_file_size,
        )

        if args.output:
            write_markdown(report, args.output)
            print(f"Markdown report written to {args.output}")
        else:
            print(render_markdown(report))

        if args.json:
            write_json(report, args.json)
            print(f"JSON report written to {args.json}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-review",
        description="Analyze a local or GitHub repository and generate a review report.",
    )
    parser.add_argument("target", help="Local repository path or GitHub URL")
    parser.add_argument("-o", "--output", type=Path, help="Write Markdown report to this path")
    parser.add_argument("--json", type=Path, help="Write structured JSON report to this path")
    parser.add_argument("--max-files", type=int, default=500, help="Maximum number of files to scan")
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=512_000,
        help="Maximum file size, in bytes, to read during the scan",
    )
    return parser


class resolve_target:
    def __init__(self, target: str) -> None:
        self.target = target
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if _looks_like_git_url(self.target):
            self._tmpdir = tempfile.TemporaryDirectory(prefix="repo-review-")
            clone_path = Path(self._tmpdir.name) / "repo"
            subprocess.run(
                ["git", "clone", "--depth", "1", self.target, str(clone_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
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


if __name__ == "__main__":
    sys.exit(main())
