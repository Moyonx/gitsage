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


class ExplainStep(BaseModel):
    """One iteration of the explain Agent loop.

    The agent either requests more data (done=False) or delivers the final
    explanation (done=True).
    """

    thinking: str = Field(
        description="Agent's reasoning about what to do next"
    )
    action: Literal["get_commit", "get_pr", "get_issue", "read_file", "done"] = Field(
        description="Tool to call, or 'done' to deliver final explanation"
    )
    params: dict = Field(
        default_factory=dict,
        description="Parameters for the action (e.g. {'sha': 'abc123'} or {'pr_number': 89})",
    )
    done: bool = Field(
        description="True when the agent has enough context to explain"
    )
    # Populated when done=True
    explanation: str = Field(
        default="",
        description="Final explanation of why the code exists (only when done=True)",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="Confidence in the explanation (only when done=True)",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Commit SHAs, PR/Issue numbers referenced (only when done=True)",
    )
