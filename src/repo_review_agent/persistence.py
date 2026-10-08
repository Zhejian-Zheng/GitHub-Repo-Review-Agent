"""Safe report projection shared by synchronous and durable history writes."""

from __future__ import annotations

from .models import ReviewReport
from .redaction import redact_data


def history_payload(
    *,
    report: ReviewReport,
    repo_url: str,
    report_markdown: str,
    owner_id: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> dict:
    return redact_data(
        {
            "repo_url": repo_url,
            "repo_name": report.repo_name,
            "owner_id": owner_id,
            "branch": branch,
            "commit_sha": commit_sha or report.metrics.get("source_commit_sha"),
            "report": report.to_dict(),
            "report_markdown": report_markdown,
        }
    )


def restore_report(data: dict) -> ReviewReport:
    """Restore a persisted report for presentation, preserving its evidence identity."""
    from dataclasses import fields

    from .models import AgentStep, AIReview, Finding

    def construct(cls, value):
        return cls(**{f.name: value[f.name] for f in fields(cls) if f.name in value})

    return ReviewReport(
        repo_name=data.get("repo_name", "repository"),
        generated_at=data.get("generated_at", ""),
        overview=data.get("overview", []),
        metrics=data.get("metrics", {}),
        framework_signals=data.get("framework_signals", {}),
        findings=[construct(Finding, f) for f in data.get("findings", [])],
        raw_findings=[construct(Finding, f) for f in data.get("raw_findings", [])],
        policy_decisions=data.get("policy_decisions", []),
        ai_review=construct(AIReview, data["ai_review"]) if data.get("ai_review") else None,
        agent_trace=[construct(AgentStep, step) for step in data.get("agent_trace") or []],
        finding_feedback=data.get("finding_feedback", []),
    )
