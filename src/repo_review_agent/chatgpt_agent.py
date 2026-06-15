from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .function_agent import OpenAIFunctionCallingAgent
from .models import ReviewReport

CHATGPT_API_PROVIDER = "chatgpt-api"


class ChatGPTReviewAgent:
    """Repository review agent backed by the OpenAI Responses API.

    This is the user-facing ChatGPT API agent. It delegates the actual tool loop
    to OpenAIFunctionCallingAgent, then labels the AI review provider in reports
    with a clearer product-facing name.
    """

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
        self._agent = OpenAIFunctionCallingAgent(
            model=model,
            timeout=timeout,
            max_turns=max_turns,
            max_output_tokens=max_output_tokens,
            max_files=max_files,
            max_file_size=max_file_size,
            report_language=report_language,
        )

    def run(self, root: Path) -> ReviewReport:
        report = self._agent.run(root)
        if report.ai_review is None:
            return report
        return replace(
            report,
            ai_review=replace(report.ai_review, provider=CHATGPT_API_PROVIDER),
        )
