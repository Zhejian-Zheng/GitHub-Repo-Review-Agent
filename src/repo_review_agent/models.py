from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .redaction import redact_data


@dataclass(frozen=True)
class RepoFile:
    path: str
    size_bytes: int
    suffix: str
    kind: str
    language: str | None = None


@dataclass(frozen=True)
class RepositorySnapshot:
    root: str
    name: str
    files: list[RepoFile]
    top_level_items: list[str]
    dependency_files: list[str]
    ci_files: list[str]
    docs_files: list[str]
    test_files: list[str]
    source_files: list[str]
    language_counts: dict[str, int]
    total_size_bytes: int
    skipped_files: int
    skipped_file_paths: list[str] = field(default_factory=list)
    # Inventory includes oversized and unsampled files; files is the content sample.
    # None supports snapshots constructed by older callers.
    inventory_files: list[RepoFile] | None = None
    inventory_complete: bool = True


@dataclass(frozen=True)
class Finding:
    title: str
    severity: str
    category: str
    evidence: list[str]
    recommendation: str
    evidence_paths: list[str] = field(default_factory=list)
    source: str = "rule"
    rule_id: str | None = None
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    confidence: float | None = None
    fingerprint: str | None = None


@dataclass(frozen=True)
class AIReview:
    provider: str
    model: str
    status: str
    summary: str
    error: str | None = None
    sections: dict[str, list[str]] | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentStep:
    thought: str
    tool: str
    tool_input: dict[str, Any]
    observation: str


@dataclass(frozen=True)
class ReviewReport:
    repo_name: str
    generated_at: str
    overview: list[str]
    metrics: dict[str, Any]
    framework_signals: dict[str, list[str]]
    findings: list[Finding]
    ai_review: AIReview | None = None
    agent_trace: list[AgentStep] | None = None

    finding_feedback: list[dict[str, Any]] = field(default_factory=list)
    raw_findings: list[Finding] = field(default_factory=list)
    policy_decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from .findings import review_findings

        result = asdict(self)
        result["findings"] = [asdict(item) for item in review_findings(self)]
        return redact_data(result)
