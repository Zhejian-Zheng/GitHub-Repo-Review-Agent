"""Compatibility entry point; all execution is owned by the LangChain agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .agent import RepoReviewAgent
from .config import ReviewConfig
from .models import ReviewReport


class OpenAIFunctionCallingAgent:
    """Legacy OpenAI mode backed by the shared LangChain tool-calling runtime."""

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
        run_linters: bool = False,
        on_progress: Callable[[str], None] | None = None,
        ai_token_budget: int | None = None,
        review_config: ReviewConfig | None = None,
        vulnerability_scan: bool = False,
        changed_files: list[dict] | None = None,
    ) -> None:
        self._agent = RepoReviewAgent(
            ai_provider="openai",
            ai_model=model,
            ai_timeout=timeout,
            max_turns=max_turns,
            ai_max_output_tokens=max_output_tokens,
            max_files=max_files,
            max_file_size=max_file_size,
            report_language=report_language,
            run_linters=run_linters,
            on_progress=on_progress,
            ai_token_budget=ai_token_budget,
            review_config=review_config,
            vulnerability_scan=vulnerability_scan,
            changed_files=changed_files,
            fail_on_ai_error=True,
        )

    def run(self, root: Path) -> ReviewReport:
        report = self._agent.run(root)
        return replace(report, ai_review=replace(report.ai_review, provider="openai-functions"))
