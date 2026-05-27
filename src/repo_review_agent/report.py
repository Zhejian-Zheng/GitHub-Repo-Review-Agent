from __future__ import annotations

import json
from pathlib import Path

from .models import Finding, ReviewReport


def render_markdown(report: ReviewReport) -> str:
    lines: list[str] = [
        f"# Repository Review: {report.repo_name}",
        "",
        f"Generated: `{report.generated_at}`",
        "",
        "## Executive Summary",
        "",
    ]

    lines.extend(f"- {item}" for item in report.overview)
    lines.extend(["", "## Metrics", ""])
    lines.extend(_render_metrics(report.metrics))
    lines.extend(["", "## Framework Signals", ""])

    if report.framework_signals:
        for label, evidence in sorted(report.framework_signals.items()):
            lines.append(f"- **{label}**: {', '.join(evidence[:4])}")
    else:
        lines.append("- No framework signals were detected.")

    if report.ai_review:
        lines.extend(["", "## AI Review", ""])
        lines.append(f"- Provider: `{report.ai_review.provider}`")
        lines.append(f"- Model: `{report.ai_review.model}`")
        lines.append(f"- Status: `{report.ai_review.status}`")
        lines.append("")
        if report.ai_review.status == "generated":
            lines.append(report.ai_review.summary)
        else:
            lines.append(f"AI review was not generated: `{report.ai_review.error}`")
        lines.append("")

    lines.extend(["", "## Findings", ""])
    for index, finding in enumerate(report.findings, start=1):
        lines.extend(_render_finding(index, finding))

    lines.extend(["", "## GitHub Issue Backlog", ""])
    for finding in report.findings:
        if finding.severity == "info":
            continue
        lines.append(f"- [{finding.severity.upper()}] {finding.title} - {finding.recommendation}")

    if all(finding.severity == "info" for finding in report.findings):
        lines.append("- No immediate issue suggestions.")

    lines.append("")
    return "\n".join(lines)


def write_json(report: ReviewReport, output_path: Path) -> None:
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_markdown(report: ReviewReport, output_path: Path) -> None:
    output_path.write_text(render_markdown(report), encoding="utf-8")


def _render_metrics(metrics: dict) -> list[str]:
    lines = [
        f"- Files scanned: `{metrics['files_scanned']}`",
        f"- Files skipped: `{metrics['files_skipped']}`",
        f"- Source files: `{metrics['source_files']}`",
        f"- Test files: `{metrics['test_files']}`",
        f"- Dependency manifests: `{metrics['dependency_files']}`",
        f"- CI files: `{metrics['ci_files']}`",
    ]

    languages = metrics.get("languages", {})
    if languages:
        language_text = ", ".join(f"{name}: {count}" for name, count in languages.items())
        lines.append(f"- Languages: `{language_text}`")
    else:
        lines.append("- Languages: `none detected`")

    return lines


def _render_finding(index: int, finding: Finding) -> list[str]:
    lines = [
        f"### {index}. {finding.title}",
        "",
        f"- Severity: `{finding.severity}`",
        f"- Category: `{finding.category}`",
        "- Evidence:",
    ]
    lines.extend(f"  - {item}" for item in finding.evidence)
    lines.extend(["- Recommendation:", f"  - {finding.recommendation}", ""])
    return lines
