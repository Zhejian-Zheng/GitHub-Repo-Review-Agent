"""Application input contracts shared by HTTP handlers and isolated workers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .security import int_from_env


def _default_max_files() -> int:
    return min(500, int_from_env("REPO_REVIEW_MAX_FILES_LIMIT", 1000, minimum=1))


def _default_max_file_size() -> int:
    return min(512_000, int_from_env("REPO_REVIEW_MAX_FILE_SIZE_LIMIT", 1_000_000, minimum=1024))


class ReviewRequest(BaseModel):
    target: str = Field(..., description="Local repository path or GitHub URL.")
    mode: Literal["direct", "agent", "function-calling"] = "agent"
    ai_provider: Literal["none", "openai", "openrouter", "anthropic", "ollama"] = "none"
    ai_model: str | None = None
    report_language: Literal["en", "zh-CN"] = "en"
    max_files: int = Field(default_factory=_default_max_files, ge=1)
    max_file_size: int = Field(default_factory=_default_max_file_size, ge=1_024)
    ai_token_budget: int = Field(20_000, ge=256, le=200_000)
    vulnerability_scan: bool = False
    lint: bool = False
    save_history: bool = False
    history_repo_url: str | None = None

    @field_validator("max_files", "max_file_size")
    @classmethod
    def configured_limits(cls, value, info):
        limits = {
            "max_files": ("REPO_REVIEW_MAX_FILES_LIMIT", 1000, 1),
            "max_file_size": ("REPO_REVIEW_MAX_FILE_SIZE_LIMIT", 1_000_000, 1024),
        }
        name, default, minimum = limits[info.field_name]
        if value > int_from_env(name, default, minimum=minimum):
            raise ValueError(f"{info.field_name} exceeds the configured limit.")
        return value


class FindingFeedbackRequest(BaseModel):
    status: Literal["confirmed", "false_positive", "ignored"]
    reason: str = Field("", max_length=2000)
    expires_at: datetime | None = None


class ReportQuestionRequest(BaseModel):
    job_id: str | None = None
    report: dict[str, Any] | None = None
    question: str = Field(..., min_length=1, max_length=2000)
    provider: Literal["none", "openai", "openrouter", "anthropic", "ollama"] = "none"
    model: str | None = None
    language: Literal["en", "zh-CN"] = "en"
    token_budget: int = Field(4000, ge=256, le=20_000)


