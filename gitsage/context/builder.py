from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .git_reader import GitReader, GitState
from .ctx_reader import CTXReader, CTXContent
from .memory import MemoryManager


@dataclass
class CommitContext:
    git_state: GitState
    ctx: CTXContent
    memory_content: str
    skill_content: str


@dataclass
class StandupContext:
    git_state: GitState
    ctx: CTXContent
    memory_content: str
    skill_content: str
    date_str: str


@dataclass
class PRContext:
    git_state: GitState
    ctx: CTXContent
    base_branch: str


class ContextBuilder:
    """Assemble rich context objects for each gitsage command.

    Orchestrates GitReader, CTXReader, and MemoryManager into the
    typed context dataclasses consumed by the agent prompts.
    """

    def __init__(self, path: Path = None):
        self._path = path or Path.cwd()
        self._git = GitReader(self._path)
        self._ctx_reader = CTXReader(self._path)

    # ------------------------------------------------------------------
    # Public builders
    # ------------------------------------------------------------------

    def build_commit_context(self, skill_content: str = "") -> CommitContext:
        """Build context for the commit message generation command."""
        git_state = self._git.get_state()
        ctx = self._ctx_reader.read()
        memory = MemoryManager(git_state.repo_name)
        return CommitContext(
            git_state=git_state,
            ctx=ctx,
            memory_content=memory.read(),
            skill_content=skill_content,
        )

    def build_standup_context(self, skill_content: str = "") -> StandupContext:
        """Build context for the standup report generation command."""
        git_state = self._git.get_state()
        ctx = self._ctx_reader.read()
        memory = MemoryManager(git_state.repo_name)
        date_str = date.today().isoformat()
        return StandupContext(
            git_state=git_state,
            ctx=ctx,
            memory_content=memory.read(),
            skill_content=skill_content,
            date_str=date_str,
        )

    def build_pr_context(self, base_branch: str = "main") -> PRContext:
        """Build context for pull request description generation.

        Fetches a broader commit history so the PR prompt has full branch
        context. The base_branch is recorded for the diff boundary.
        """
        # Use a higher commit limit for PR context
        git_state = self._git.get_state(commit_limit=50)
        ctx = self._ctx_reader.read()
        return PRContext(
            git_state=git_state,
            ctx=ctx,
            base_branch=base_branch,
        )
