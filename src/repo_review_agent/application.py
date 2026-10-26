"""Review use cases, independent of the HTTP transport and job scheduler."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .auth import AuthUser
from .history import SupabaseHistoryStore
from .i18n import localize_report
from .report import public_report_dict, render_markdown
from .requests import ReviewRequest
from .service import run_review
from .targets import resolve_target


def execute_review_request(request: ReviewRequest, user: AuthUser | None,
                           on_progress: Callable[[str], None] | None = None, *,
                           defer_history: bool = False) -> dict:
    if on_progress:
        on_progress("cloning")
    with resolve_target(request.target) as repo_path:
        if on_progress:
            on_progress("analyzing")
        report = run_review_for_path(request, repo_path, **({"on_progress": on_progress} if on_progress else {}))

    history_result = None
    pending_history = None
    if request.save_history:
        if user is None:
            raise PermissionError("Sign in before saving review history.")
        arguments = dict(report=report, repo_url=request.history_repo_url or request.target,
                         report_markdown=render_markdown(report, language=request.report_language),
                         owner_id=user.id)
        if defer_history:
            from .persistence import history_payload
            pending_history = history_payload(**arguments)
        else:
            history_result = SupabaseHistoryStore.from_env().save_report(**arguments)

    if history_result:
        report = replace(report, finding_feedback=history_result.finding_feedback)
    report = localize_report(report, request.report_language)
    response = {
        "markdown": render_markdown(report, language=request.report_language),
        "report": public_report_dict(report),
    }
    if pending_history is not None:
        response["_pending_history"] = pending_history
    if history_result:
        response["history"] = history_result.to_dict()
    return response


def run_review_for_path(request: ReviewRequest, repo_path: Path, on_progress=None):
    return run_review(
        repo_path, mode=request.mode, max_files=request.max_files,
        max_file_size=request.max_file_size, ai_provider=request.ai_provider,
        ai_model=request.ai_model, report_language=request.report_language,
        run_linters=request.lint, ai_token_budget=request.ai_token_budget,
        vulnerability_scan=request.vulnerability_scan,
        **({"on_progress": on_progress} if on_progress else {}),
    )


