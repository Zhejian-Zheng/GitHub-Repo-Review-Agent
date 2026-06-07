from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .models import Finding, RepositorySnapshot, ReviewReport
from .scanner import read_text_file, scan_repository


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

PLACEHOLDER_SECRET_TERMS = {
    "your_",
    "your-",
    "example",
    "placeholder",
    "dummy",
    "changeme",
    "change_me",
    "replace_me",
    "replace-this",
}

JS_LOCKFILE_NAMES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
}

CI_TEST_TERMS = {
    "pytest",
    "python -m unittest",
    "unittest discover",
    "npm test",
    "npm run test",
    "pnpm test",
    "yarn test",
    "vitest",
    "jest",
    "go test",
    "cargo test",
    "mvn test",
    "gradle test",
}

CI_BUILD_TERMS = {
    "npm run build",
    "pnpm build",
    "yarn build",
    "vite build",
    "python -m build",
    "docker build",
    "go build",
    "cargo build",
    "mvn package",
    "gradle build",
}

README_SETUP_TERMS = {
    "install",
    "setup",
    "getting started",
    "quick start",
    "usage",
    "run",
    "docker",
    "npm",
    "pip",
    "poetry",
    "uv",
    "安装",
    "启动",
    "使用",
}

README_OUTPUT_TERMS = {
    "demo",
    "example",
    "sample",
    "output",
    "report",
    "screenshot",
    "演示",
    "示例",
    "输出",
    "报告",
    "截图",
}


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
    dependency_paths = {path.lower() for path in snapshot.dependency_files}
    package_jsons_missing_lockfile = _package_jsons_missing_lockfile(dependency_paths, file_paths)

    if "readme.md" not in file_paths:
        findings.append(
            Finding(
                title="Add a README with setup and usage instructions",
                severity="high",
                category="documentation",
                evidence=["README.md was not found."],
                recommendation="Add a concise README that explains the project goal, setup steps, commands, and sample output.",
                evidence_paths=["README.md"],
            )
        )
    else:
        readme_findings = build_readme_quality_findings(root)
        findings.extend(readme_findings)

    if not any(path in {"license", "license.md"} for path in file_paths):
        findings.append(
            Finding(
                title="Add an explicit open-source license",
                severity="medium",
                category="project hygiene",
                evidence=["No LICENSE file was detected."],
                recommendation="Add a LICENSE file so users know how they can use and adapt the code.",
                evidence_paths=["LICENSE"],
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
                evidence_paths=[".gitignore"],
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
                evidence_paths=_first_paths(snapshot.source_files),
            )
        )
    elif len(snapshot.source_files) >= 4 and snapshot.test_files:
        test_ratio = len(snapshot.test_files) / len(snapshot.source_files)
        if test_ratio < 0.25:
            findings.append(
                Finding(
                    title="Expand test coverage across source modules",
                    severity="medium",
                    category="testing",
                    evidence=[
                        f"Only {len(snapshot.test_files)} test file(s) were found for {len(snapshot.source_files)} source file(s)."
                    ],
                    recommendation="Add focused tests for the main source modules and track coverage thresholds in CI.",
                    evidence_paths=_first_paths(snapshot.test_files, snapshot.source_files),
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
                evidence_paths=_first_paths(snapshot.source_files, snapshot.dependency_files),
            )
        )
    elif snapshot.ci_files:
        ci_findings = build_ci_quality_findings(snapshot, root)
        findings.extend(ci_findings)

    if snapshot.source_files and not snapshot.dependency_files:
        findings.append(
            Finding(
                title="Add a dependency manifest",
                severity="medium",
                category="maintainability",
                evidence=["No package manager manifest was detected."],
                recommendation="Add pyproject.toml, package.json, go.mod, or the equivalent manifest for the stack.",
                evidence_paths=_first_paths(snapshot.source_files),
            )
        )

    if package_jsons_missing_lockfile:
        findings.append(
            Finding(
                title="Commit a JavaScript package lockfile",
                severity="medium",
                category="dependency hygiene",
                evidence=["package.json was found without package-lock.json, pnpm-lock.yaml, yarn.lock, or bun.lock."],
                recommendation="Commit the package manager lockfile so dependency resolution is reproducible in CI and deployments.",
                evidence_paths=package_jsons_missing_lockfile,
            )
        )

    docker_findings = build_docker_quality_findings(snapshot, root)
    findings.extend(docker_findings)

    if snapshot.skipped_files:
        findings.append(
            Finding(
                title="Review skipped files",
                severity="low",
                category="analysis coverage",
                evidence=[f"{snapshot.skipped_files} file(s) were skipped because of limits or read errors."],
                recommendation="Increase scan limits or inspect skipped files manually if they are relevant to the review.",
                evidence_paths=snapshot.skipped_file_paths[:5],
            )
        )

    secret_evidence = find_secret_like_values(snapshot, root)
    if secret_evidence:
        secret_evidence_sample = secret_evidence[:5]
        findings.insert(
            0,
            Finding(
                title="Remove possible hard-coded secrets",
                severity="high",
                category="security",
                evidence=secret_evidence_sample,
                recommendation="Move credentials into environment variables or a secret manager, then rotate exposed values.",
                evidence_paths=_paths_from_prefixed_evidence(secret_evidence_sample),
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
                evidence_paths=_first_paths(
                    snapshot.docs_files,
                    snapshot.dependency_files,
                    snapshot.test_files,
                    snapshot.ci_files,
                    [
                        file.path
                        for file in snapshot.files
                        if file.path.lower() in {"readme.md", "license", "license.md", ".gitignore"}
                    ],
                    limit=8,
                ),
            )
        )

    return findings


def build_readme_quality_findings(root: Path) -> list[Finding]:
    text = read_text_file(root, "README.md", limit=80_000)
    normalized = text.lower()
    missing: list[str] = []

    if not any(term in normalized for term in README_SETUP_TERMS):
        missing.append("setup or usage instructions")
    if not any(term in normalized for term in README_OUTPUT_TERMS):
        missing.append("example output, demo, or screenshots")

    if not missing:
        return []

    return [
        Finding(
            title="Expand README with setup and example output",
            severity="low",
            category="documentation",
            evidence=[f"README.md is missing {', '.join(missing)}."],
            recommendation="Add installation steps, run commands, and a small report/demo screenshot so reviewers can understand the project quickly.",
            evidence_paths=["README.md"],
        )
    ]


def build_ci_quality_findings(snapshot: RepositorySnapshot, root: Path) -> list[Finding]:
    combined_ci = "\n".join(
        read_text_file(root, ci_file, limit=80_000).lower()
        for ci_file in snapshot.ci_files[:8]
    )
    findings: list[Finding] = []

    if snapshot.source_files and not any(term in combined_ci for term in CI_TEST_TERMS):
        findings.append(
            Finding(
                title="Run automated tests in CI",
                severity="medium",
                category="delivery",
                evidence=[f"CI files were found ({', '.join(snapshot.ci_files[:3])}), but no common test command was detected."],
                recommendation="Add language-specific test commands to CI so regressions are caught before merge.",
                evidence_paths=snapshot.ci_files[:3],
            )
        )

    frontend_package_paths = _frontend_package_paths(snapshot)
    if frontend_package_paths and not any(term in combined_ci for term in CI_BUILD_TERMS):
        findings.append(
            Finding(
                title="Build frontend assets in CI",
                severity="medium",
                category="delivery",
                evidence=["A JavaScript frontend package was detected, but CI does not appear to run a frontend build command."],
                recommendation="Run npm run build, pnpm build, or the equivalent frontend build command in CI.",
                evidence_paths=_first_paths(snapshot.ci_files, frontend_package_paths),
            )
        )

    return findings


def build_docker_quality_findings(snapshot: RepositorySnapshot, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    dockerfiles = [file.path for file in snapshot.files if file.path.lower().endswith("dockerfile")]

    for dockerfile in dockerfiles[:3]:
        text = read_text_file(root, dockerfile, limit=80_000)
        if not _dockerfile_sets_non_root_user(text):
            findings.append(
                Finding(
                    title="Harden Docker image with a non-root runtime user",
                    severity="low",
                    category="security",
                    evidence=[f"{dockerfile} does not set a non-root USER before runtime."],
                    recommendation="Create and switch to an application user in the final Docker stage to reduce container privilege risk.",
                    evidence_paths=[dockerfile],
                )
            )
            break

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
            matches = [match.group(0) for match in pattern.finditer(text)]
            real_matches = [
                match for match in matches if not _looks_like_secret_placeholder(match)
            ]
            if real_matches:
                evidence.append(f"{file.path}: secret-like value matched {pattern.pattern!r}")
                break

    return evidence


def _looks_like_secret_placeholder(match_text: str) -> bool:
    normalized = match_text.lower()
    return any(term in normalized for term in PLACEHOLDER_SECRET_TERMS)


def _has_package_json_without_lockfile(
    dependency_paths: set[str],
    file_paths: set[str],
) -> bool:
    return bool(_package_jsons_missing_lockfile(dependency_paths, file_paths))


def _package_jsons_missing_lockfile(
    dependency_paths: set[str],
    file_paths: set[str],
) -> list[str]:
    missing_package_jsons: list[str] = []
    package_dirs = {
        str(Path(path).parent).replace("\\", "/")
        for path in dependency_paths
        if Path(path).name == "package.json"
    }
    for package_dir in sorted(package_dirs):
        package_dir = "" if package_dir == "." else package_dir
        package_json = f"{package_dir}/package.json" if package_dir else "package.json"
        for lockfile in JS_LOCKFILE_NAMES:
            candidate = f"{package_dir}/{lockfile}" if package_dir else lockfile
            if candidate.lower() in file_paths:
                break
        else:
            missing_package_jsons.append(package_json)
    return missing_package_jsons


def _has_frontend_package(snapshot: RepositorySnapshot) -> bool:
    return bool(_frontend_package_paths(snapshot))


def _frontend_package_paths(snapshot: RepositorySnapshot) -> list[str]:
    return [path for path in snapshot.dependency_files if path.lower().endswith("package.json")]


def _first_paths(*path_groups: Iterable[str], limit: int = 5) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for path_group in path_groups:
        for path in path_group:
            if not path or path in seen:
                continue
            paths.append(path)
            seen.add(path)
            if len(paths) >= limit:
                return paths
    return paths


def _paths_from_prefixed_evidence(evidence: Iterable[str]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        path, separator, _ = item.partition(":")
        if not separator or not path or path in seen:
            continue
        paths.append(path)
        seen.add(path)
    return paths


def _dockerfile_sets_non_root_user(text: str) -> bool:
    last_user: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"(?i)^USER\s+(.+)$", stripped)
        if match:
            last_user = match.group(1).strip().split(":", 1)[0].strip()
    return last_user is not None and last_user not in {"0", "root"}


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
