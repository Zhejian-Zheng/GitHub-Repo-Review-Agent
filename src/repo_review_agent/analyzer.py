from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .models import Finding, RepositorySnapshot, ReviewReport
from .scanner import read_text_file, scan_repository


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def analyze_repository(
    root: Path,
    *,
    max_files: int = 500,
    max_file_size: int = 512_000,
) -> ReviewReport:
    snapshot = scan_repository(root, max_files=max_files, max_file_size=max_file_size)
    return analyze_snapshot(snapshot, root)


def analyze_snapshot(snapshot: RepositorySnapshot, root: Path) -> ReviewReport:
    framework_signals = detect_framework_signals(snapshot, root)
    findings = build_findings(snapshot, root)

    return ReviewReport(
        repo_name=snapshot.name,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        overview=build_overview(snapshot, framework_signals),
        metrics={
            "files_scanned": len(snapshot.files),
            "files_skipped": snapshot.skipped_files,
            "total_size_bytes": snapshot.total_size_bytes,
            "source_files": len(snapshot.source_files),
            "test_files": len(snapshot.test_files),
            "dependency_files": len(snapshot.dependency_files),
            "ci_files": len(snapshot.ci_files),
            "top_level_items": snapshot.top_level_items,
            "languages": snapshot.language_counts,
        },
        framework_signals=framework_signals,
        findings=findings,
    )


def build_overview(
    snapshot: RepositorySnapshot,
    framework_signals: dict[str, list[str]],
) -> list[str]:
    overview: list[str] = []
    languages = sorted(
        snapshot.language_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    if languages:
        language_text = ", ".join(f"{name} ({count})" for name, count in languages[:4])
        overview.append(f"Primary source languages detected: {language_text}.")
    else:
        overview.append("No application source files were detected in the scanned sample.")

    if snapshot.dependency_files:
        overview.append(
            "Dependency manifests found: " + ", ".join(snapshot.dependency_files[:6]) + "."
        )
    else:
        overview.append("No dependency manifest was found.")

    if snapshot.test_files:
        overview.append(f"Test coverage surface detected through {len(snapshot.test_files)} test file(s).")
    else:
        overview.append("No test files were detected.")

    if snapshot.ci_files:
        overview.append("CI configuration detected: " + ", ".join(snapshot.ci_files[:4]) + ".")
    else:
        overview.append("No CI workflow files were detected.")

    if framework_signals:
        frameworks = ", ".join(sorted(framework_signals))
        overview.append(f"Framework and tooling signals: {frameworks}.")

    return overview


def detect_framework_signals(
    snapshot: RepositorySnapshot,
    root: Path,
) -> dict[str, list[str]]:
    signals: dict[str, list[str]] = {}

    for rel_path in snapshot.dependency_files:
        text = read_text_file(root, rel_path).lower()
        if not text:
            continue

        if rel_path.endswith("package.json"):
            _detect_package_json(signals, root, rel_path)
            continue

        _detect_by_terms(
            signals,
            rel_path,
            text,
            {
                "OpenAI": ["openai", "agents"],
                "LangChain": ["langchain", "langgraph"],
                "LlamaIndex": ["llama-index", "llama_index"],
                "FastAPI": ["fastapi"],
                "Flask": ["flask"],
                "Django": ["django"],
                "Pytest": ["pytest"],
                "Pydantic": ["pydantic"],
                "PostgreSQL": ["psycopg", "asyncpg", "postgres"],
                "Docker": ["docker"],
                "React": ["react"],
                "Next.js": ["next"],
            },
        )

    for ci_file in snapshot.ci_files:
        signals.setdefault("CI/CD", []).append(ci_file)

    if any(file.path.lower() == "dockerfile" for file in snapshot.files):
        signals.setdefault("Docker", []).append("Dockerfile")

    return signals


def build_findings(snapshot: RepositorySnapshot, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    file_paths = {file.path.lower() for file in snapshot.files}

    if "readme.md" not in file_paths:
        findings.append(
            Finding(
                title="Add a README with setup and usage instructions",
                severity="high",
                category="documentation",
                evidence=["README.md was not found."],
                recommendation="Add a concise README that explains the project goal, setup steps, commands, and sample output.",
            )
        )

    if not any(path in {"license", "license.md"} for path in file_paths):
        findings.append(
            Finding(
                title="Add an explicit open-source license",
                severity="medium",
                category="project hygiene",
                evidence=["No LICENSE file was detected."],
                recommendation="Add a LICENSE file so users know how they can use and adapt the code.",
            )
        )

    if ".gitignore" not in file_paths:
        findings.append(
            Finding(
                title="Add a .gitignore file",
                severity="low",
                category="project hygiene",
                evidence=[".gitignore was not found."],
                recommendation="Ignore virtual environments, caches, build outputs, local reports, and secrets.",
            )
        )

    if snapshot.source_files and not snapshot.test_files:
        findings.append(
            Finding(
                title="Add automated tests for the core behavior",
                severity="medium",
                category="testing",
                evidence=[f"{len(snapshot.source_files)} source file(s) found, but no tests were detected."],
                recommendation="Add small tests around the scanner and analyzer so regressions are caught before release.",
            )
        )

    if snapshot.source_files and not snapshot.ci_files:
        findings.append(
            Finding(
                title="Add a CI workflow",
                severity="medium",
                category="delivery",
                evidence=["No workflow file was found under .github/workflows or other common CI locations."],
                recommendation="Run tests and basic import checks on pull requests using GitHub Actions.",
            )
        )

    if snapshot.source_files and not snapshot.dependency_files:
        findings.append(
            Finding(
                title="Add a dependency manifest",
                severity="medium",
                category="maintainability",
                evidence=["No package manager manifest was detected."],
                recommendation="Add pyproject.toml, package.json, go.mod, or the equivalent manifest for the stack.",
            )
        )

    if snapshot.skipped_files:
        findings.append(
            Finding(
                title="Review skipped files",
                severity="low",
                category="analysis coverage",
                evidence=[f"{snapshot.skipped_files} file(s) were skipped because of limits or read errors."],
                recommendation="Increase scan limits or inspect skipped files manually if they are relevant to the review.",
            )
        )

    secret_evidence = find_secret_like_values(snapshot, root)
    if secret_evidence:
        findings.insert(
            0,
            Finding(
                title="Remove possible hard-coded secrets",
                severity="high",
                category="security",
                evidence=secret_evidence[:5],
                recommendation="Move credentials into environment variables or a secret manager, then rotate exposed values.",
            ),
        )

    if not findings:
        findings.append(
            Finding(
                title="No major project hygiene gaps detected",
                severity="info",
                category="summary",
                evidence=["README, license, dependency metadata, tests, and CI signals were present in the scan."],
                recommendation="Continue with deeper checks such as dependency vulnerability scanning and coverage thresholds.",
            )
        )

    return findings


def find_secret_like_values(snapshot: RepositorySnapshot, root: Path) -> list[str]:
    evidence: list[str] = []
    candidate_files = [
        file
        for file in snapshot.files
        if file.kind in {"source", "dependency", "project-meta", "ops", "other"}
        and file.suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip"}
    ]

    for file in candidate_files[:250]:
        text = read_text_file(root, file.path, limit=80_000)
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                evidence.append(f"{file.path}: secret-like value matched {pattern.pattern!r}")
                break

    return evidence


def _detect_package_json(signals: dict[str, list[str]], root: Path, rel_path: str) -> None:
    text = read_text_file(root, rel_path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        signals.setdefault("JavaScript tooling", []).append(f"{rel_path} could not be parsed")
        return

    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps.update(data.get(key, {}))

    package_terms = {
        "React": ["react"],
        "Next.js": ["next"],
        "Vue": ["vue"],
        "Vite": ["vite"],
        "Express": ["express"],
        "NestJS": ["@nestjs/core"],
        "TypeScript": ["typescript"],
        "Jest": ["jest", "vitest"],
        "Playwright": ["playwright", "@playwright/test"],
        "OpenAI": ["openai"],
        "LangChain": ["langchain", "@langchain/core"],
    }

    for label, packages in package_terms.items():
        matched = [package for package in packages if package in deps]
        if matched:
            signals.setdefault(label, []).append(f"{rel_path}: {', '.join(matched)}")


def _detect_by_terms(
    signals: dict[str, list[str]],
    rel_path: str,
    text: str,
    terms_by_label: dict[str, list[str]],
) -> None:
    for label, terms in terms_by_label.items():
        matched = [term for term in terms if term in text]
        if matched:
            signals.setdefault(label, []).append(f"{rel_path}: {', '.join(matched)}")
