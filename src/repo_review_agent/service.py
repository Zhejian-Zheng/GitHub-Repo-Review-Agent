"""Shared review routing for CLI, HTTP and MCP consumers."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .agent import RepoReviewAgent
from .analyzer import analyze_repository, analyze_snapshot
from .chatgpt_agent import ChatGPTReviewAgent
from .config import ReviewConfig, apply_review_config, load_review_config
from .function_agent import OpenAIFunctionCallingAgent
from .incremental import diff_summary, normalize_changed_files
from .llm import AIProviderError, add_ai_review, attach_ai_error
from .models import ReviewReport
from .scanner import scan_repository
from .vulnerabilities import scan_vulnerabilities


def run_review(
    root: Path,
    *,
    mode: str = "agent",
    max_files: int = 500,
    max_file_size: int = 512_000,
    ai_provider: str = "none",
    ai_model: str | None = None,
    ai_timeout: float = 60,
    ai_max_output_tokens: int = 900,
    ollama_url: str | None = None,
    fail_on_ai_error: bool = False,
    report_language: str | None = None,
    run_linters: bool = False,
    on_progress: Callable[[str], None] | None = None,
    ai_token_budget: int | None = None,
    vulnerability_scan: bool = False,
    config_path: Path | None = None,
    trust_repository_config: bool = False,
    changed_files: list[dict] | None = None,
) -> ReviewReport:
    if ai_token_budget is not None and ai_token_budget <= 0:
        raise ValueError("AI token budget must be positive.")
    config = load_review_config(root, config_path) if config_path is not None or trust_repository_config else ReviewConfig()
    if config_path is None and not trust_repository_config:
        config._source = "builtin"
    changed_files = normalize_changed_files(changed_files)
    common = dict(
        max_files=max_files,
        max_file_size=max_file_size,
        report_language=report_language,
        run_linters=run_linters,
    )
    common["review_config"] = config
    if changed_files is not None:
        common["changed_files"] = changed_files
    if vulnerability_scan:
        common['vulnerability_scan'] = True
    if ai_token_budget is not None:
        common["ai_token_budget"] = ai_token_budget
    if on_progress is not None:
        common["on_progress"] = on_progress
    if mode in ("function-calling", "chatgpt-agent"):
        adapter = OpenAIFunctionCallingAgent if mode == "function-calling" else ChatGPTReviewAgent
        return _with_source_metadata(root, adapter(
            model=ai_model, timeout=ai_timeout, max_output_tokens=ai_max_output_tokens, **common
        ).run(root))
    if mode == "agent":
        return _with_source_metadata(root, RepoReviewAgent(
            ai_provider=ai_provider,
            ai_model=ai_model,
            ai_timeout=ai_timeout,
            ai_max_output_tokens=ai_max_output_tokens,
            ollama_url=ollama_url,
            fail_on_ai_error=fail_on_ai_error,
            **common,
        ).run(root))
    if mode != "direct":
        raise ValueError(f"Unsupported review mode: {mode}")
    if on_progress:
        on_progress("analyzing")
    report = (analyze_snapshot(scan_repository(root, max_files=max_files, max_file_size=max_file_size,
                                              ignore_patterns=config.ignore,
                                              priority_paths=[i["filename"] for i in changed_files or []]), root, run_linters=run_linters)
              if config.ignore or changed_files is not None else analyze_repository(root, max_files=max_files, max_file_size=max_file_size,
                                                        run_linters=run_linters))
    if vulnerability_scan:
        result = scan_vulnerabilities(root, ignore_patterns=config.ignore)
        report = replace(report, findings=[*report.findings, *result.findings], metrics={
            **report.metrics, 'vulnerability_scan': {'status':result.status, 'details':result.details,
            'checked_packages':result.checked_packages, 'total_packages':result.total_packages}
        })
    report = apply_review_config(report, config)
    if changed_files is not None:
        report = replace(report, metrics={**report.metrics,"review_scope":"incremental","changed_files":diff_summary(changed_files)})
    if ai_provider != "none":
        try:
            if on_progress:
                on_progress("ai")
            report = add_ai_review(
                report,
                provider=ai_provider,
                model=ai_model,
                language=report_language,
                timeout=ai_timeout,
                max_output_tokens=ai_max_output_tokens,
                ollama_url=ollama_url,
                token_budget=ai_token_budget,
            )
        except AIProviderError as exc:
            if fail_on_ai_error:
                raise
            report = attach_ai_error(report, provider=ai_provider, model=ai_model, error=str(exc))
    return _with_source_metadata(root, report)


def _with_source_metadata(root: Path, report: ReviewReport) -> ReviewReport:
    try:
        commit = subprocess.run(['git', '-c', 'core.fsmonitor=false', 'rev-parse', '--verify', 'HEAD'],
                                cwd=root, capture_output=True, text=True, check=True, timeout=2).stdout.strip()
        status = subprocess.run(['git', '-c', 'core.fsmonitor=false', '--no-optional-locks', 'status',
                                 '--porcelain', '--untracked-files=normal'],
                                cwd=root, capture_output=True, text=True, check=True, timeout=2).stdout
        if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
            return replace(report, metrics={**report.metrics,'source_commit_sha':commit,'source_dirty':bool(status)})
    except (OSError, subprocess.SubprocessError):
        pass
    return report
