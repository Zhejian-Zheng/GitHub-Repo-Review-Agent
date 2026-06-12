from __future__ import annotations

from collections import Counter
from pathlib import Path

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
) -> RepositorySnapshot:
    root = root.resolve()
    files: list[RepoFile] = []
    skipped_files = 0
    skipped_file_paths: list[str] = []

    for path in _iter_files(root):
        try:
            stat = path.stat()
        except OSError:
            skipped_files += 1
            skipped_file_paths.append(_relative_path(root, path))
            continue

        rel_path = _relative_path(root, path)
        if stat.st_size > max_file_size:
            skipped_files += 1
            skipped_file_paths.append(rel_path)
            continue

        suffix = path.suffix.lower()
        language = LANGUAGE_BY_SUFFIX.get(suffix)
        kind = _classify_file(rel_path, path.name, language)
        files.append(
            RepoFile(
                path=rel_path,
                size_bytes=stat.st_size,
                suffix=suffix,
                kind=kind,
                language=language,
            )
        )

        if len(files) >= max_files:
            skipped_files += 1
            skipped_file_paths.append(rel_path)
            break

    language_counts = Counter(
        file.language
        for file in files
        if file.kind == "source" and file.language in SOURCE_LANGUAGES
    )

    top_level_items = sorted(
        item.name
        for item in root.iterdir()
        if item.name not in IGNORED_DIRS and item.name != ".git"
    )

    return RepositorySnapshot(
        root=str(root),
        name=root.name,
        files=files,
        top_level_items=top_level_items,
        dependency_files=sorted(file.path for file in files if file.kind == "dependency"),
        ci_files=sorted(file.path for file in files if file.kind == "ci"),
        docs_files=sorted(file.path for file in files if file.kind == "docs"),
        test_files=sorted(file.path for file in files if file.kind == "test"),
        source_files=sorted(file.path for file in files if file.kind == "source"),
        language_counts=dict(language_counts),
        total_size_bytes=sum(file.size_bytes for file in files),
        skipped_files=skipped_files,
        skipped_file_paths=skipped_file_paths,
    )


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
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
    path = (root / rel_path).resolve()
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""
