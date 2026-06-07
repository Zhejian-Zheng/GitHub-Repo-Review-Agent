from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .analyzer import analyze_snapshot
from .i18n import ai_section_headings, language_display_name, normalize_report_language
from .llm import (
    AIProviderError,
    OPENAI_RESPONSES_URL,
    _post_json,
    extract_openai_text,
    parse_ai_review_sections,
    render_ai_review_sections,
    resolve_model,
)
from .models import AIReview, AgentStep, RepositorySnapshot, ReviewReport
from .report import render_markdown
from .scanner import read_text_file, scan_repository


FUNCTION_CALLING_TOOLS = [
    {
        "type": "function",
        "name": "scan_repository",
        "description": "Scan the repository and return structured counts, file groups, and language signals.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "inspect_file",
        "description": "Inspect a repository file by relative path and return a concise preview.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative path to inspect, for example README.md or pyproject.toml.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to read from the file.",
                },
            },
            "required": ["path", "max_chars"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "analyze_repository",
        "description": "Run deterministic risk analysis after repository scanning and file inspection.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "generate_report",
        "description": "Render the current analysis report and return a Markdown preview.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["markdown"],
                    "description": "Report format to render.",
                }
            },
            "required": ["format"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class FunctionCallingState:
    root: Path
    snapshot: RepositorySnapshot | None = None
    inspected_files: dict[str, str] | None = None
    report: ReviewReport | None = None
    rendered_report: str | None = None

    def __post_init__(self) -> None:
        if self.inspected_files is None:
            self.inspected_files = {}


@dataclass(frozen=True)
class FunctionCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


class OpenAIFunctionCallingAgent:
    """Model-driven repository review agent using OpenAI function calling."""

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout: float = 60,
        max_turns: int = 8,
        max_output_tokens: int = 900,
        max_files: int = 500,
        max_file_size: int = 512_000,
        report_language: str | None = None,
    ) -> None:
        self.model = resolve_model("openai", model)
        self.timeout = timeout
        self.max_turns = max_turns
        self.max_output_tokens = max_output_tokens
        self.max_files = max_files
        self.max_file_size = max_file_size
        self.report_language = normalize_report_language(report_language)

    def run(self, root: Path) -> ReviewReport:
        if not os.environ.get("OPENAI_API_KEY"):
            raise AIProviderError("OPENAI_API_KEY is not set.")

        state = FunctionCallingState(root=root.resolve())
        trace: list[AgentStep] = []
        input_items: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    "Review this repository as a hiring-portfolio AI agent. "
                    "Use tools before answering. First scan the repository, inspect important files, "
                    "run deterministic analysis, generate a report preview, then return structured JSON."
                    f" Write all JSON string values in {language_display_name(self.report_language)}."
                ),
            }
        ]

        final_text = ""
        for _ in range(self.max_turns):
            response = self._create_response(input_items)
            output = response.get("output", [])
            if isinstance(output, list):
                input_items.extend(output)

            calls = extract_function_calls(response)
            if not calls:
                final_text = extract_openai_text(response)
                break

            for call in calls:
                result = self._execute_tool(state, call)
                result_json = json.dumps(result, ensure_ascii=False)
                trace.append(
                    AgentStep(
                        thought="The model requested this tool through OpenAI function calling.",
                        tool=call.name,
                        tool_input=call.arguments,
                        observation=_summarize_tool_result(result),
                    )
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": result_json,
                    }
                )

        if state.report is None:
            raise AIProviderError("Function-calling agent stopped before producing a report.")

        if final_text.strip():
            try:
                sections = parse_ai_review_sections(final_text, language=self.report_language)
                summary = render_ai_review_sections(sections, language=self.report_language)
                ai_review = AIReview(
                    provider="openai-functions",
                    model=self.model,
                    status="generated",
                    summary=summary,
                    sections=sections,
                )
            except AIProviderError as exc:
                ai_review = AIReview(
                    provider="openai-functions",
                    model=self.model,
                    status="error",
                    summary="",
                    error=str(exc),
                )
        else:
            ai_review = AIReview(
                provider="openai-functions",
                model=self.model,
                status="error",
                summary="",
                error="Model did not return a final text response.",
            )
        return replace(state.report, ai_review=ai_review, agent_trace=trace)

    def _create_response(self, input_items: list[dict[str, Any]]) -> dict:
        return _post_json(
            OPENAI_RESPONSES_URL,
            {
                "model": self.model,
                "input": input_items,
                "tools": FUNCTION_CALLING_TOOLS,
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "max_output_tokens": self.max_output_tokens,
                "instructions": (
                    "You are a senior software engineer. Use the provided functions for repository facts. "
                    "Do not invent files or findings. After generate_report, return only a valid JSON object "
                    "with exactly these top-level keys: architecture_summary, risks, project_highlights, next_steps. "
                    "Each value must be an array of non-empty plain-text strings with no Markdown headings, "
                    "bullet markers, empty strings, or resume/self-promotion content. The backend will render "
                    "Markdown with these sections: "
                    f"{', '.join(ai_section_headings(self.report_language))}. "
                    f"Write all JSON string values in {language_display_name(self.report_language)}."
                ),
            },
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        )

    def _execute_tool(self, state: FunctionCallingState, call: FunctionCall) -> dict[str, Any]:
        if call.name == "scan_repository":
            return self._scan_repository(state)
        if call.name == "inspect_file":
            return self._inspect_file(state, call.arguments)
        if call.name == "analyze_repository":
            return self._analyze_repository(state)
        if call.name == "generate_report":
            return self._generate_report(state, call.arguments)
        return {"ok": False, "error": f"Unknown tool: {call.name}"}

    def _scan_repository(self, state: FunctionCallingState) -> dict[str, Any]:
        state.snapshot = scan_repository(
            state.root,
            max_files=self.max_files,
            max_file_size=self.max_file_size,
        )
        snapshot = state.snapshot
        return {
            "ok": True,
            "repo_name": snapshot.name,
            "files_scanned": len(snapshot.files),
            "source_files": len(snapshot.source_files),
            "test_files": len(snapshot.test_files),
            "dependency_files": snapshot.dependency_files[:8],
            "ci_files": snapshot.ci_files[:8],
            "docs_files": snapshot.docs_files[:8],
            "languages": snapshot.language_counts,
            "recommended_files_to_inspect": recommend_files_to_inspect(snapshot),
        }

    def _inspect_file(
        self,
        state: FunctionCallingState,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        rel_path = str(arguments.get("path", ""))
        max_chars = int(arguments.get("max_chars", 4000))

        if not is_safe_relative_path(state.root, rel_path):
            return {"ok": False, "path": rel_path, "error": "Path is outside the repository."}

        content = read_text_file(state.root, rel_path, limit=max_chars)
        if state.inspected_files is None:
            state.inspected_files = {}
        state.inspected_files[rel_path] = content

        return {
            "ok": True,
            "path": rel_path,
            "line_count": content.count("\n") + (1 if content else 0),
            "preview": compact_preview(content, max_chars=900),
        }

    def _analyze_repository(self, state: FunctionCallingState) -> dict[str, Any]:
        if state.snapshot is None:
            self._scan_repository(state)

        if state.snapshot is None:
            return {"ok": False, "error": "Repository scan failed."}

        report = analyze_snapshot(state.snapshot, state.root)
        inspected_files = sorted((state.inspected_files or {}).keys())
        state.report = replace(
            report,
            metrics={
                **report.metrics,
                "agent_inspected_files": inspected_files,
                "agent_mode": "openai_function_calling",
            },
        )
        return {
            "ok": True,
            "findings": [
                {
                    "title": finding.title,
                    "severity": finding.severity,
                    "category": finding.category,
                    "recommendation": finding.recommendation,
                }
                for finding in state.report.findings
            ],
        }

    def _generate_report(
        self,
        state: FunctionCallingState,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if arguments.get("format") != "markdown":
            return {"ok": False, "error": "Only markdown format is supported."}
        if state.report is None:
            analysis_result = self._analyze_repository(state)
            if not analysis_result.get("ok"):
                return analysis_result

        if state.report is None:
            return {"ok": False, "error": "Report is unavailable."}

        state.rendered_report = render_markdown(state.report, language=self.report_language)
        return {
            "ok": True,
            "format": "markdown",
            "preview": state.rendered_report[:3000],
        }


def extract_function_calls(response: dict[str, Any]) -> list[FunctionCall]:
    calls: list[FunctionCall] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue

        raw_args = item.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:
            arguments = {}

        calls.append(
            FunctionCall(
                call_id=str(item.get("call_id", "")),
                name=str(item.get("name", "")),
                arguments=arguments,
            )
        )
    return calls


def recommend_files_to_inspect(snapshot: RepositorySnapshot) -> list[str]:
    candidates: list[str] = []
    paths = {file.path for file in snapshot.files}

    for name in ("README.md", "readme.md"):
        if name in paths:
            candidates.append(name)
            break

    candidates.extend(snapshot.dependency_files[:3])
    candidates.extend(snapshot.ci_files[:2])

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique[:6]


def is_safe_relative_path(root: Path, rel_path: str) -> bool:
    if not rel_path or Path(rel_path).is_absolute():
        return False
    try:
        resolved = (root / rel_path).resolve()
        return resolved.is_relative_to(root.resolve()) and resolved.is_file()
    except OSError:
        return False


def compact_preview(content: str, *, max_chars: int = 900) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    preview = "\n".join(lines[:40]).strip()
    if len(preview) > max_chars:
        return preview[: max_chars - 3] + "..."
    return preview


def _summarize_tool_result(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"Tool failed: {result.get('error', 'unknown error')}"
    if "files_scanned" in result:
        return (
            f"Scanned {result['files_scanned']} file(s); "
            f"source={result['source_files']}, tests={result['test_files']}."
        )
    if "path" in result:
        return f"Inspected {result['path']} with {result.get('line_count', 0)} line(s)."
    if "findings" in result:
        return f"Generated {len(result['findings'])} finding(s)."
    if "preview" in result:
        return "Rendered Markdown report preview."
    return "Tool completed."
