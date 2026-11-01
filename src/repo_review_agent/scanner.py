from __future__ import annotations

import logging
import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .config import path_is_ignored
from .models import RepoFile, RepositorySnapshot
from .security import int_from_env

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".terraform",
}

# Test fixture / sample-data directories. Their contents are deliberate examples
# (often intentionally broken), not the project's own code, so they are excluded
# from the scan to avoid false-positive hygiene and security findings.
FIXTURE_DIRS = {
    "fixtures",
    "__fixtures__",
    "testdata",
}

EXCLUDED_DIRS = IGNORED_DIRS | FIXTURE_DIRS

DEPENDENCY_FILES = {
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
}

SOURCE_LANGUAGES = {
    "Python",
    "JavaScript",
    "TypeScript",
    "Go",
    "Rust",
    "Java",
    "Kotlin",
    "C#",
    "Ruby",
    "PHP",
    "Swift",
    "C",
    "C/C++",
    "C++",
}

DOC_NAMES = {"readme", "contributing", "changelog", "architecture", "docs"}


def scan_repository(
    root: Path,
    *,
    max_files: int = 500,
    max_file_size: int = 512_000,
    ignore_patterns: list[str] | tuple[str, ...] = (),
    priority_paths: list[str] | tuple[str, ...] = (),
) -> RepositorySnapshot:
    root = root.resolve()
    inventory: list[RepoFile] = []
    skipped_file_paths: list[str] = []
    walk_errors: list[OSError] = []
    uninspected_paths: list[str] = []
    top_level_items: list[str] = []
    inventory_limit = int_from_env("REPO_REVIEW_MAX_INVENTORY_FILES", 10_000, minimum=1)
    walk_limit = int_from_env("REPO_REVIEW_MAX_WALK_ENTRIES", 50_000, minimum=1)
    budget_exceeded = False

    try:
        for path in _iter_files(root, onerror=walk_errors.append, ignore_patterns=ignore_patterns,
                                onexcluded=uninspected_paths.append, max_entries=walk_limit,
                                ontoplevel=top_level_items.append):
            if len(inventory) >= inventory_limit:
                raise InventoryLimitError("Repository inventory file budget exceeded.")
            rel_path = _relative_path(root, path)
            try:
                metadata = path.lstat()
            except OSError as error:
                walk_errors.append(error)
                skipped_file_paths.append(rel_path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                uninspected_paths.append(rel_path)
                continue
            suffix = path.suffix.lower()
            language = LANGUAGE_BY_SUFFIX.get(suffix)
            inventory.append(RepoFile(
                path=rel_path, size_bytes=metadata.st_size, suffix=suffix,
                kind=_classify_file(rel_path, path.name, language), language=language,
            ))
    except InventoryLimitError as error:
        budget_exceeded = True
        uninspected_paths.append(".")  # The unvisited remainder is unknown, not an exact skipped count.
        logging.getLogger(__name__).warning("%s", error)

    # Keep a bounded path inventory and separately bound files eligible for content
    # inspection. Important metadata takes precedence over alphabetical source files.
    def priority(file: RepoFile) -> tuple[int, str, str]:
        name = file.path.lower()
        rank = (
            -1 if file.path in priority_paths else
            0 if name == "readme.md" else
            1 if name in {"license", "license.md"} else
            2 if file.kind in {"dependency", "ci", "project-meta", "ops"} else
            3 if file.kind == "test" else 4
        )
        return rank, name, file.path

    files: list[RepoFile] = []
    for file in sorted(inventory, key=priority):
        if file.size_bytes > max_file_size or len(files) >= max_files:
            skipped_file_paths.append(file.path)
        else:
            files.append(file)
    files.sort(key=lambda file: (file.path.lower(), file.path))
    skipped_file_paths.sort()
    language_counts = Counter(
        file.language for file in inventory
        if file.kind == "source" and file.language in SOURCE_LANGUAGES
    )
    top_level_items.sort()
    return RepositorySnapshot(
        root=str(root), name=root.name, files=files, top_level_items=top_level_items,
        dependency_files=sorted(file.path for file in inventory if file.kind == "dependency"),
        ci_files=sorted(file.path for file in inventory if file.kind == "ci"),
        docs_files=sorted(file.path for file in inventory if file.kind == "docs"),
        test_files=sorted(file.path for file in inventory if file.kind == "test"),
        source_files=sorted(file.path for file in inventory if file.kind == "source"),
        language_counts=dict(language_counts),
        total_size_bytes=sum(file.size_bytes for file in files),
        skipped_files=len(skipped_file_paths), skipped_file_paths=skipped_file_paths,
        inventory_files=inventory, inventory_complete=not walk_errors and not budget_exceeded,
        uninspected_paths=uninspected_paths,
    )


class InventoryLimitError(RuntimeError):
    """Traversal stopped before the complete repository could be inspected."""


def _iter_files(root: Path, *, onerror: Callable[[OSError], None] | None = None,
                ignore_patterns: Sequence[str] = (), onexcluded: Callable[[str], None] | None = None,
                max_entries: int = 50_000, ontoplevel: Callable[[str], None] | None = None,
                ) -> Iterator[Path]:
    # os.walk builds a full directory listing before yielding. Bound scandir
    # buffering (including excluded entries) before sorting for stable selection.
    pending = [root]
    visited = 0
    while pending:
        directory = pending.pop()
        entries = []
        try:
            with os.scandir(directory) as stream:
                for entry in stream:
                    visited += 1
                    if visited > max_entries:
                        raise InventoryLimitError("Repository walk entry budget exceeded.")
                    entries.append(entry)
        except OSError as error:
            if onerror:
                onerror(error)
            continue
        directories = []
        for entry in sorted(entries, key=lambda item: item.name):
            path = Path(entry.path)
            relative = _relative_path(root, path)
            try:
                if entry.is_symlink():
                    if onexcluded:
                        onexcluded(relative)
                    continue
                if path_is_ignored(relative, ignore_patterns):
                    continue
                is_directory = entry.is_dir(follow_symlinks=False)
                if is_directory and entry.name in EXCLUDED_DIRS:
                    continue
                if directory == root and ontoplevel:
                    ontoplevel(entry.name)
                if is_directory:
                    directories.append(path)
                else:
                    yield path
            except OSError as error:
                if onerror:
                    onerror(error)
        pending.extend(reversed(directories))


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _classify_file(rel_path: str, name: str, language: str | None) -> str:
    lower_path = rel_path.lower()
    lower_name = name.lower()

    if name in DEPENDENCY_FILES:
        return "dependency"
    if lower_path.startswith(".github/workflows/") or lower_name in {
        ".gitlab-ci.yml",
        ".gitlab-ci.yaml",
        "azure-pipelines.yml",
        "circle.yml",
        "jenkinsfile",
    }:
        return "ci"
    if (
        lower_name.startswith("test_")
        or lower_name.endswith("_test.py")
        or lower_name.endswith((".test.js", ".test.jsx", ".spec.js", ".spec.jsx"))
        or lower_name.endswith(".test.ts")
        or lower_name.endswith(".test.tsx")
        or lower_name.endswith(".spec.ts")
        or lower_name.endswith(".spec.tsx")
        or "/tests/" in f"/{lower_path}/"
        or "/test/" in f"/{lower_path}/"
    ):
        return "test"
    if lower_name in {"dockerfile", "compose.yml", "docker-compose.yml"}:
        return "ops"
    if lower_name in {"readme.md", "license", "license.md", ".gitignore"}:
        return "project-meta"
    if language in SOURCE_LANGUAGES:
        return "source"
    if language == "Markdown" or lower_path.startswith("docs/") or lower_name.split(".")[0] in DOC_NAMES:
        return "docs"
    return "other"


_INCOMPLETE_READS: ContextVar[set[str] | None] = ContextVar('incomplete_reads', default=None)


@contextmanager
def track_incomplete_reads():
    incomplete: set[str] = set()
    token = _INCOMPLETE_READS.set(incomplete)
    try:
        yield incomplete
    finally:
        _INCOMPLETE_READS.reset(token)


def read_text_file(root: Path, rel_path: str, *, limit: int = 60_000) -> str:
    root = root.resolve()
    candidate = root / rel_path
    incomplete = _INCOMPLETE_READS.get()
    previously_incomplete = incomplete is not None and rel_path in incomplete
    if incomplete is not None:
        incomplete.add(rel_path)
    try:
        relative = candidate.relative_to(root)
        if ".." in relative.parts:
            return ""
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return ""
        if not candidate.is_file():
            return ""
        with candidate.open("r", encoding="utf-8", errors="replace") as stream:
            text = stream.read(max(0, limit))
            if incomplete is not None and not previously_incomplete and text.strip() and len(text) < limit:
                incomplete.discard(rel_path)
            return text
    except (OSError, ValueError):
        return ""
