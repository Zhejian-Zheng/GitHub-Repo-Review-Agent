"""Schema for newly generated reviews (historical report parsing is separate)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ReviewText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ReviewItems = Annotated[list[ReviewText], Field(min_length=1, max_length=20)]


class EvidenceFinding(BaseModel):
    """A code claim whose quoted lines must have been exposed by a repository tool."""

    model_config = ConfigDict(extra="forbid")
    title: ReviewText
    severity: Literal["high", "medium", "low", "info"]
    path: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=8000)]
    confidence: float = Field(ge=0, le=1)
    recommendation: ReviewText


class ReviewSections(BaseModel):
    """Evidence-backed repository review, written in the requested report language."""

    model_config = ConfigDict(extra="forbid")

    architecture_summary: ReviewItems
    risks: ReviewItems
    project_highlights: ReviewItems
    next_steps: ReviewItems

    findings: list[EvidenceFinding] = Field(default_factory=list, max_length=20)
