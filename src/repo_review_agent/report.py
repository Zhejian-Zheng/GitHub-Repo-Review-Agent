from __future__ import annotations

import json
from pathlib import Path

from .i18n import localize_report, normalize_report_language
from .models import Finding, ReviewReport


REPORT_LABELS = {
    "en": {
        "title": "Repository Review",
        "generated": "Generated",
        "summary": "Executive Summary",
        "metrics": "Metrics",
        "frameworks": "Framework Signals",
        "no_frameworks": "No framework signals were detected.",
        "ai_review": "AI Review",
        "provider": "Provider",
        "model": "Model",
        "status": "Status",
        "ai_error": "AI review was not generated",
        "agent_trace": "Agent Trace",
        "step": "Step",
        "thought": "Thought",
        "input": "Input",
        "observation": "Observation",
        "findings": "Findings",
        "severity": "Severity",
        "category": "Category",
        "evidence": "Evidence",
        "recommendation": "Recommendation",
        "issue_backlog": "GitHub Issue Backlog",
        "no_issues": "No immediate issue suggestions.",
        "files_scanned": "Files scanned",
        "files_skipped": "Files skipped",
        "source_files": "Source files",
        "test_files": "Test files",
        "dependency_files": "Dependency manifests",
        "ci_files": "CI files",
        "languages": "Languages",
        "none_detected": "none detected",
    },
    "zh-CN": {
        "title": "仓库评审",
        "generated": "生成时间",
        "summary": "执行摘要",
        "metrics": "指标",
        "frameworks": "框架信号",
        "no_frameworks": "未检测到框架信号。",
        "ai_review": "AI 评审",
        "provider": "提供方",
        "model": "模型",
        "status": "状态",
        "ai_error": "AI 评审未生成",
        "agent_trace": "Agent 执行轨迹",
        "step": "步骤",
        "thought": "思考",
        "input": "输入",
        "observation": "观察",
        "findings": "发现",
        "severity": "严重程度",
        "category": "类别",
        "evidence": "证据",
        "recommendation": "建议",
        "issue_backlog": "GitHub Issue 待办",
        "no_issues": "暂无需要立即创建的 Issue 建议。",
        "files_scanned": "扫描文件数",
        "files_skipped": "跳过文件数",
        "source_files": "源码文件数",
        "test_files": "测试文件数",
        "dependency_files": "依赖清单数",
        "ci_files": "CI 文件数",
        "languages": "语言",
        "none_detected": "未检测到",
    },
}


def render_markdown(report: ReviewReport, *, language: str | None = None) -> str:
    language = normalize_report_language(language)
    labels = REPORT_LABELS[language]
    report = localize_report(report, language)

    lines: list[str] = [
        f"# {labels['title']}: {report.repo_name}",
        "",
        f"{labels['generated']}: `{report.generated_at}`",
        "",
        f"## {labels['summary']}",
        "",
    ]

    lines.extend(f"- {item}" for item in report.overview)
    lines.extend(["", f"## {labels['metrics']}", ""])
    lines.extend(_render_metrics(report.metrics, labels))
    lines.extend(["", f"## {labels['frameworks']}", ""])

    if report.framework_signals:
        for label, evidence in sorted(report.framework_signals.items()):
            lines.append(f"- **{label}**: {', '.join(evidence[:4])}")
    else:
        lines.append(f"- {labels['no_frameworks']}")

    if report.ai_review:
        lines.extend(["", f"## {labels['ai_review']}", ""])
        lines.append(f"- {labels['provider']}: `{report.ai_review.provider}`")
        lines.append(f"- {labels['model']}: `{report.ai_review.model}`")
        lines.append(f"- {labels['status']}: `{report.ai_review.status}`")
        lines.append("")
        if report.ai_review.status == "generated":
            lines.append(report.ai_review.summary)
        else:
            lines.append(f"{labels['ai_error']}: `{report.ai_review.error}`")
        lines.append("")

    if report.agent_trace:
        lines.extend(["", f"## {labels['agent_trace']}", ""])
        for index, step in enumerate(report.agent_trace, start=1):
            lines.append(f"### {labels['step']} {index}: `{step.tool}`")
            lines.append("")
            lines.append(f"- {labels['thought']}: {step.thought}")
            lines.append(f"- {labels['input']}: `{json.dumps(step.tool_input, ensure_ascii=False)}`")
            lines.append(f"- {labels['observation']}: {step.observation}")
            lines.append("")

    lines.extend(["", f"## {labels['findings']}", ""])
    for index, finding in enumerate(report.findings, start=1):
        lines.extend(_render_finding(index, finding, labels))

    lines.extend(["", f"## {labels['issue_backlog']}", ""])
    for finding in report.findings:
        if finding.severity == "info":
            continue
        lines.append(f"- [{finding.severity.upper()}] {finding.title} - {finding.recommendation}")

    if all(finding.severity == "info" for finding in report.findings):
        lines.append(f"- {labels['no_issues']}")

    lines.append("")
    return "\n".join(lines)


def write_json(report: ReviewReport, output_path: Path) -> None:
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_markdown(
    report: ReviewReport,
    output_path: Path,
    *,
    language: str | None = None,
) -> None:
    output_path.write_text(render_markdown(report, language=language), encoding="utf-8")


def _render_metrics(metrics: dict, labels: dict[str, str]) -> list[str]:
    lines = [
        f"- {labels['files_scanned']}: `{metrics['files_scanned']}`",
        f"- {labels['files_skipped']}: `{metrics['files_skipped']}`",
        f"- {labels['source_files']}: `{metrics['source_files']}`",
        f"- {labels['test_files']}: `{metrics['test_files']}`",
        f"- {labels['dependency_files']}: `{metrics['dependency_files']}`",
        f"- {labels['ci_files']}: `{metrics['ci_files']}`",
    ]

    languages = metrics.get("languages", {})
    if languages:
        language_text = ", ".join(f"{name}: {count}" for name, count in languages.items())
        lines.append(f"- {labels['languages']}: `{language_text}`")
    else:
        lines.append(f"- {labels['languages']}: `{labels['none_detected']}`")

    return lines


def _render_finding(index: int, finding: Finding, labels: dict[str, str]) -> list[str]:
    lines = [
        f"### {index}. {finding.title}",
        "",
        f"- {labels['severity']}: `{finding.severity}`",
        f"- {labels['category']}: `{finding.category}`",
        f"- {labels['evidence']}:",
    ]
    lines.extend(f"  - {item}" for item in finding.evidence)
    lines.extend([f"- {labels['recommendation']}:", f"  - {finding.recommendation}", ""])
    return lines
