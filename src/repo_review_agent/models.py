from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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


@dataclass(frozen=True)
class Finding:
    title: str
    severity: str
    category: str
    evidence: list[str]
    recommendation: str


@dataclass(frozen=True)
class AIReview:
    provider: str
    model: str
    status: str
    summary: str
    error: str | None = None
    sections: dict[str, list[str]] | None = None


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
