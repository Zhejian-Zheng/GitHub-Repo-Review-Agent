from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .analyzer import analyze_snapshot
from .i18n import normalize_report_language
from .llm import AIProviderError, add_ai_review, attach_ai_error
from .models import AgentStep, RepositorySnapshot, ReviewReport
from .report import render_markdown
from .scanner import read_text_file, scan_repository


@dataclass(frozen=True)
class ToolCall:
    thought: str
    name: str
    args: dict[str, Any]


@dataclass
class AgentState:
    root: Path
    snapshot: RepositorySnapshot | None = None
    inspected_files: dict[str, str] | None = None
    report: ReviewReport | None = None
    report_preview: str | None = None
    finalized: bool = False

    def __post_init__(self) -> None:
        if self.inspected_files is None:
            self.inspected_files = {}


ToolHandler = Callable[[AgentState, dict[str, Any]], str]


class RepoReviewAgent:
    """A small custom agent that calls repository-review tools in a traceable loop."""

    def __init__(
        self,
        *,
        max_files: int = 500,
        max_file_size: int = 512_000,
        max_steps: int = 12,
        ai_provider: str = "none",
        ai_model: str | None = None,
        ai_timeout: float = 60,
        ai_max_output_tokens: int = 900,
        ollama_url: str | None = None,
        fail_on_ai_error: bool = False,
        report_language: str | None = None,
    ) -> None:
        self.max_files = max_files
        self.max_file_size = max_file_size
        self.max_steps = max_steps
        self.ai_provider = ai_provider
        self.ai_model = ai_model
        self.ai_timeout = ai_timeout
        self.ai_max_output_tokens = ai_max_output_tokens
        self.ollama_url = ollama_url
        self.fail_on_ai_error = fail_on_ai_error
        self.report_language = normalize_report_language(report_language)
        self.tools: dict[str, ToolHandler] = {
            "scan_repository": self._tool_scan_repository,
            "inspect_file": self._tool_inspect_file,
            "analyze_repository": self._tool_analyze_repository,
            "generate_ai_review": self._tool_generate_ai_review,
            "finalize_report": self._tool_finalize_report,
        }

    def run(self, root: Path) -> ReviewReport:
        state = AgentState(root=root.resolve())
        trace: list[AgentStep] = []

        for _ in range(self.max_steps):
            tool_call = self._plan_next_tool(state)
            if tool_call is None:
                break

            tool = self.tools[tool_call.name]
            observation = tool(state, tool_call.args)
            trace.append(
                AgentStep(
                    thought=tool_call.thought,
                    tool=tool_call.name,
                    tool_input=tool_call.args,
                    observation=observation,
                )
            )

            if state.finalized:
                break

        if state.report is None:
            raise RuntimeError("Agent stopped before producing a review report.")

        return replace(state.report, agent_trace=trace)

    def _plan_next_tool(self, state: AgentState) -> ToolCall | None:
        if state.snapshot is None:
            return ToolCall(
                thought="I need a structured map of the repository before making review decisions.",
                name="scan_repository",
                args={"path": str(state.root)},
            )

        next_file = self._next_file_to_inspect(state)
        if next_file is not None:
            return ToolCall(
                thought="I should inspect important project files before producing risk findings.",
                name="inspect_file",
                args={"path": next_file, "max_chars": 4000},
            )

        if state.report is None:
            return ToolCall(
                thought="I have enough repository context to run deterministic risk analysis.",
                name="analyze_repository",
                args={"path": str(state.root)},
            )

        if self.ai_provider != "none" and state.report.ai_review is None:
            return ToolCall(
                thought="The structured findings are ready, so I can ask the selected model to synthesize the review.",
                name="generate_ai_review",
                args={"provider": self.ai_provider, "model": self.ai_model},
            )

        if not state.finalized:
            return ToolCall(
                thought="The review report is complete and should be rendered for the user.",
                name="finalize_report",
                args={"format": "markdown"},
            )

        return None

    def _next_file_to_inspect(self, state: AgentState) -> str | None:
        if state.snapshot is None or state.inspected_files is None:
            return None

        for path in self._inspection_candidates(state.snapshot):
            if path not in state.inspected_files:
                return path
        return None

    def _inspection_candidates(self, snapshot: RepositorySnapshot) -> list[str]:
        candidates: list[str] = []
        paths = {file.path for file in snapshot.files}

        for readme_name in ("README.md", "readme.md"):
            if readme_name in paths:
                candidates.append(readme_name)
                break

        candidates.extend(snapshot.dependency_files[:3])
        candidates.extend(snapshot.ci_files[:2])
        candidates.extend(
            path
            for path in snapshot.docs_files
            if _is_helpful_doc_candidate(path)
        )

        seen: set[str] = set()
        unique_candidates: list[str] = []
        for path in candidates:
            if path not in seen:
                unique_candidates.append(path)
                seen.add(path)
        return unique_candidates[:5]

    def _tool_scan_repository(self, state: AgentState, args: dict[str, Any]) -> str:
        state.snapshot = scan_repository(
            state.root,
            max_files=self.max_files,
            max_file_size=self.max_file_size,
        )
        return (
            f"Scanned {len(state.snapshot.files)} file(s), "
            f"found {len(state.snapshot.source_files)} source file(s), "
            f"{len(state.snapshot.test_files)} test file(s), "
            f"and {len(state.snapshot.ci_files)} CI file(s)."
        )

    def _tool_inspect_file(self, state: AgentState, args: dict[str, Any]) -> str:
        rel_path = str(args["path"])
        max_chars = int(args.get("max_chars", 4000))
        content = read_text_file(state.root, rel_path, limit=max_chars)

        if state.inspected_files is None:
            state.inspected_files = {}
        state.inspected_files[rel_path] = content

        line_count = content.count("\n") + (1 if content else 0)
        preview = _compact_preview(content)
        if preview:
            return f"Inspected {rel_path}: {line_count} line(s). Preview: {preview}"
        return f"Inspected {rel_path}: file was empty or unreadable."

    def _tool_analyze_repository(self, state: AgentState, args: dict[str, Any]) -> str:
        if state.snapshot is None:
            raise RuntimeError("scan_repository must run before analyze_repository.")

        report = analyze_snapshot(state.snapshot, state.root)
        inspected_files = sorted((state.inspected_files or {}).keys())
        state.report = replace(
            report,
            metrics={
                **report.metrics,
                "agent_inspected_files": inspected_files,
            },
        )
        finding_count = len(state.report.findings)
        return f"Generated {finding_count} finding(s) after inspecting {len(inspected_files)} key file(s)."

    def _tool_generate_ai_review(self, state: AgentState, args: dict[str, Any]) -> str:
        if state.report is None:
            raise RuntimeError("analyze_repository must run before generate_ai_review.")

        provider = str(args["provider"])
        model = args.get("model")
        try:
            state.report = add_ai_review(
                state.report,
                provider=provider,
                model=model,
                language=self.report_language,
                timeout=self.ai_timeout,
                max_output_tokens=self.ai_max_output_tokens,
                ollama_url=self.ollama_url,
            )
            return f"Generated AI review with {state.report.ai_review.provider}/{state.report.ai_review.model}."
        except AIProviderError as exc:
            if self.fail_on_ai_error:
                raise
            state.report = attach_ai_error(
                state.report,
                provider=provider,
                model=model,
                error=str(exc),
            )
            return f"AI review failed but the agent preserved the base report: {exc}"

    def _tool_finalize_report(self, state: AgentState, args: dict[str, Any]) -> str:
        if state.report is None:
            raise RuntimeError("analyze_repository must run before finalize_report.")

        state.report_preview = render_markdown(state.report, language=self.report_language)[:1200]
        state.finalized = True
        return f"Rendered Markdown preview with {len(state.report_preview)} character(s)."


def _compact_preview(content: str, *, max_chars: int = 160) -> str:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return ""
    preview = " | ".join(lines[:3])
    if len(preview) > max_chars:
        return preview[: max_chars - 3] + "..."
    return preview


def _is_helpful_doc_candidate(path: str) -> bool:
    lower_path = path.lower()
    if lower_path in {"readme.md", "license.md"}:
        return False
    if lower_path.startswith("docs/example-report"):
        return False
    return lower_path.endswith(".md")
