"""Normalize external linter output into deterministic-pipeline findings.

The static analyzer in :mod:`repo_review_agent.analyzer` is intentionally
filename/heuristic based. This module is an *opt-in* enrichment layer: when the
caller asks for it (CLI ``--lint`` or the web ``lint`` flag) and the relevant
tool is available on ``PATH``, it runs the tool and folds its diagnostics into
the same :class:`~repo_review_agent.models.Finding` shape the rest of the
pipeline produces.

Only static tools that do not execute the target project's code are used, so it
remains safe to run against freshly cloned, untrusted repositories.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from .models import Finding, RepositorySnapshot

RUFF_TIMEOUT = 60
RUFF_MAX_FINDINGS = 8
RUFF_EVIDENCE_SAMPLES = 5

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


def collect_linter_findings(
    snapshot: RepositorySnapshot,
    root: Path,
    *,
    timeout: float = RUFF_TIMEOUT,
) -> list[Finding]:
    """Run available linters and return their normalized findings."""

    findings: list[Finding] = []
    if _has_python_sources(snapshot):
        findings.extend(ruff_findings(root, timeout=timeout))
    return findings


def ruff_findings(
    root: Path,
    *,
    timeout: float = RUFF_TIMEOUT,
    max_findings: int = RUFF_MAX_FINDINGS,
) -> list[Finding]:
    diagnostics = _run_ruff(root, timeout=timeout)
    if not diagnostics:
        return []

    by_code: dict[str, list[dict]] = defaultdict(list)
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        code = diagnostic.get("code") or "syntax-error"
        by_code[str(code)].append(diagnostic)

    ordered = sorted(
        by_code.items(),
        key=lambda item: (
            _SEVERITY_RANK[_ruff_severity(item[0])],
            -len(item[1]),
            item[0],
        ),
    )

    findings = [_finding_for_code(code, diags, root) for code, diags in ordered[:max_findings]]
    return findings


def _finding_for_code(code: str, diagnostics: list[dict], root: Path) -> Finding:
    severity = _ruff_severity(code)
    category = _ruff_category(code)
    count = len(diagnostics)
    message = _first_message(diagnostics)
    url = _first_url(diagnostics)

    samples = diagnostics[:RUFF_EVIDENCE_SAMPLES]
    evidence = [_format_location(diagnostic, root) for diagnostic in samples]
    if count > len(samples):
        evidence.append(f"... and {count - len(samples)} more occurrence(s).")

    recommendation = f"Resolve the Ruff {code} findings"
    if message:
        recommendation += f" ({message})"
    recommendation += "."
    if url:
        recommendation += f" See {url}."

    return Finding(
        title=f"Fix {count} Ruff {code} lint finding(s)",
        severity=severity,
        category=category,
        evidence=evidence,
        recommendation=recommendation,
        evidence_paths=_evidence_paths(diagnostics, root),
    )


def _run_ruff(root: Path, *, timeout: float) -> list:
    executable = shutil.which("ruff")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [
                executable,
                "check",
                "--output-format",
                "json",
                "--exit-zero",
                "--no-cache",
                "--quiet",
                ".",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    stdout = result.stdout.strip()
    if not stdout:
        return []
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _ruff_severity(code: str) -> str:
    if code == "syntax-error" or code.startswith("E999"):
        return "high"
    if code.startswith("S"):  # flake8-bandit security rules
        return "high"
    if code.startswith(("F", "B")):
        return "medium"
    return "low"


def _ruff_category(code: str) -> str:
    if code.startswith("S"):
        return "security"
    if code == "syntax-error" or code.startswith(("E999", "F", "B")):
        return "correctness"
    if code.startswith("PERF"):
        return "performance"
    return "maintainability"


def _format_location(diagnostic: dict, root: Path) -> str:
    path = _relative_filename(diagnostic, root)
    location = diagnostic.get("location") or {}
    row = location.get("row")
    message = str(diagnostic.get("message") or "").strip()
    where = f"{path}:{row}" if row else path
    return f"{where} {message}".strip()


def _evidence_paths(diagnostics: list[dict], root: Path) -> list[str]:
    paths: list[str] = []
    for diagnostic in diagnostics:
        path = _relative_filename(diagnostic, root)
        if path and path not in paths:
            paths.append(path)
        if len(paths) >= RUFF_EVIDENCE_SAMPLES:
            break
    return paths


def _relative_filename(diagnostic: dict, root: Path) -> str:
    filename = diagnostic.get("filename")
    if not filename:
        return ""
    candidate = Path(filename)
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.name


def _first_message(diagnostics: list[dict]) -> str:
    for diagnostic in diagnostics:
        message = str(diagnostic.get("message") or "").strip()
        if message:
            return message
    return ""


def _first_url(diagnostics: list[dict]) -> str:
    for diagnostic in diagnostics:
        url = diagnostic.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return ""


def _has_python_sources(snapshot: RepositorySnapshot) -> bool:
    if snapshot.language_counts.get("Python"):
        return True
    return any(file.suffix == ".py" for file in snapshot.files)
