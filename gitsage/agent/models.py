"""Pydantic v2 output models for gitsage agent responses."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CommitCandidate(BaseModel):
    """A single commit message candidate."""

    message: str
    confidence: Literal["high", "medium", "low"]
    reason: str


class CommitOutput(BaseModel):
    """Structured output for commit message generation."""

    candidates: list[CommitCandidate] = Field(min_length=1, max_length=3)
    warning: Optional[str] = None


class StandupOutput(BaseModel):
    """Structured output for standup report generation."""

    content: str
    items: list[str] = []


class PROutput(BaseModel):
    """Structured output for pull request description generation."""

    title: str
    description: str
    breaking_changes: list[str] = []


class ExplainOutput(BaseModel):
    """Structured output for code archaeology / explain queries."""

    explanation: str
    confidence: Literal["high", "medium", "low"]
    sources: list[str] = []
    local_only: bool = False


class CatchupOutput(BaseModel):
    """Structured output for repository catchup summaries."""

    summary: str
    highlights: list[str] = []
    period_description: str
    commit_count: int = 0
