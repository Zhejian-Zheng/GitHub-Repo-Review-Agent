from __future__ import annotations

from pathlib import Path
from typing import Any

from .cli import resolve_target
from .github import issue_drafts_from_report
from .report import render_markdown
from .service import run_review

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - optional dependency.
    FastMCP = None


def run_review_target(
    target: str,
    *,
    mode: str = "agent",
    max_files: int = 500,
    max_file_size: int = 512_000,
) -> dict[str, Any]:
    with resolve_target(target) as repo_path:
        report = _run_review_for_path(
            repo_path,
            mode=mode,
            max_files=max_files,
            max_file_size=max_file_size,
        )
    return {
        "markdown": render_markdown(report),
        "report": report.to_dict(),
    }


def _run_review_for_path(
    repo_path: Path,
    *,
    mode: str,
    max_files: int,
    max_file_size: int,
):
    if mode not in {"agent", "direct"}:
        raise ValueError("mode must be 'agent' or 'direct' for MCP tools.")
    return run_review(repo_path, mode=mode, max_files=max_files, max_file_size=max_file_size)


def create_mcp_server():
    if FastMCP is None:
        raise RuntimeError("MCP dependencies are not installed. Run `python -m pip install -e .[mcp]`.")

    mcp = FastMCP(
        "GitHub Repo Review Agent",
        instructions=(
            "Review GitHub repositories and local codebases. Tools return structured reports, "
            "issue backlogs, and architecture summaries."
        ),
    )

    @mcp.tool()
    def review_repository(target: str, mode: str = "agent") -> dict[str, Any]:
        """Review a local repository path or GitHub URL and return Markdown plus structured JSON."""
        return run_review_target(target, mode=mode)

    @mcp.tool()
    def generate_issue_backlog(target: str, mode: str = "agent") -> list[dict[str, Any]]:
        """Generate GitHub issue drafts for actionable repository review findings."""
        result = run_review_target(target, mode=mode)
        findings_report = result["report"]
        drafts = issue_drafts_from_report_dict(findings_report)
        return [draft.to_dict() for draft in drafts]

    @mcp.tool()
    def summarize_architecture(target: str, mode: str = "agent") -> dict[str, Any]:
        """Return architecture summary signals without the full Markdown report."""
        result = run_review_target(target, mode=mode)
        report = result["report"]
        return {
            "repo_name": report["repo_name"],
            "overview": report["overview"],
            "metrics": report["metrics"],
            "framework_signals": report["framework_signals"],
        }

    return mcp


def issue_drafts_from_report_dict(report_dict: dict[str, Any]):
    from dataclasses import fields

    from .models import Finding, ReviewReport

    findings = [
        Finding(**{field.name: finding[field.name] for field in fields(Finding) if field.name in finding})
        for finding in report_dict.get("findings", [])
    ]
    report = ReviewReport(
        repo_name=report_dict["repo_name"],
        generated_at=report_dict["generated_at"],
        overview=list(report_dict.get("overview", [])),
        metrics=dict(report_dict.get("metrics", {})),
        framework_signals=dict(report_dict.get("framework_signals", {})),
        findings=findings,
        finding_feedback=list(report_dict.get("finding_feedback", [])),
    )
    return issue_drafts_from_report(report)


def main() -> None:
    create_mcp_server().run()


mcp = create_mcp_server() if FastMCP is not None else None
