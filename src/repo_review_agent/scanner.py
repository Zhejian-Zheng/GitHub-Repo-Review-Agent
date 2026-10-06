from __future__ import annotations

import os
import stat
from collections import Counter
from pathlib import Path

from .config import path_is_ignored
from .models import RepoFile, RepositorySnapshot

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

    for path in _iter_files(root, onerror=walk_errors.append, ignore_patterns=ignore_patterns):
        rel_path = _relative_path(root, path)
        try:
            metadata = path.lstat()
        except OSError as error:
            walk_errors.append(error)
            skipped_file_paths.append(rel_path)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            continue
        suffix = path.suffix.lower()
        language = LANGUAGE_BY_SUFFIX.get(suffix)
        inventory.append(RepoFile(
            path=rel_path, size_bytes=metadata.st_size, suffix=suffix,
            kind=_classify_file(rel_path, path.name, language), language=language,
        ))

    # Keep a complete path inventory, but bound the files eligible for content
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
    try:
        top_level_items = sorted(
            item.name for item in root.iterdir()
            if item.name not in EXCLUDED_DIRS and not item.is_symlink()
            and not path_is_ignored(item.name, ignore_patterns)
        )
    except OSError as error:
        walk_errors.append(error)
        top_level_items = []
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
        inventory_files=inventory, inventory_complete=not walk_errors,
    )


def _iter_files(root: Path, *, onerror=None, ignore_patterns=()):
    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in EXCLUDED_DIRS and not (Path(dirpath) / name).is_symlink()
            and not path_is_ignored(_relative_path(root, Path(dirpath) / name), ignore_patterns)
        )
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if not path.is_symlink() and not path_is_ignored(_relative_path(root, path), ignore_patterns):
                yield path


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


def read_text_file(root: Path, rel_path: str, *, limit: int = 60_000) -> str:
    root = root.resolve()
    candidate = root / rel_path
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
            return stream.read(max(0, limit))
    except (OSError, ValueError):
        return ""
