"""Catchup agent - summarizes recent repository changes."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..config import LLMConfig
from ..context.git_reader import GitReader, CommitInfo
from ..context.ctx_reader import CTXReader
from .llm import BaseLLMClient, create_llm_client
from .models import CatchupOutput
from .prompts import CATCHUP_SYSTEM_PROMPT, build_catchup_user_prompt


class CatchupAgent:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self._llm = llm_client

    @classmethod
    def from_config(cls, llm_config: LLMConfig) -> "CatchupAgent":
        return cls(create_llm_client(llm_config))

    def catchup(
        self,
        days: int = 7,
        since_tag: str = "",
        since_date: str = "",
        repo_path: Path = None,
    ) -> CatchupOutput:
        root = repo_path or Path.cwd()
        git_reader = GitReader(root)
        ctx_reader = CTXReader(root)

        # Get commits in range
        commits = self._get_commits(git_reader, days, since_tag, since_date)
        period_description = self._describe_period(days, since_tag, since_date)

        if not commits:
            return CatchupOutput(
                summary="No commits found in this period.",
                highlights=[],
                period_description=period_description,
                commit_count=0,
            )

        ctx = ctx_reader.read()
        state = git_reader.get_state(commit_limit=1)
        repo_name = state.repo_name

        user_prompt = build_catchup_user_prompt(
            commits=commits,
            period_description=period_description,
            repo_name=repo_name,
            ctx_content=ctx.raw,
        )

        output = self._llm.complete(
            system=CATCHUP_SYSTEM_PROMPT,
            user=user_prompt,
            output_model=CatchupOutput,
        )
        output.commit_count = len(commits)
        output.period_description = period_description
        return output

    def _get_commits(
        self,
        git_reader: GitReader,
        days: int,
        since_tag: str,
        since_date: str,
    ) -> list[CommitInfo]:
        import git as gitlib

        repo = gitlib.Repo(git_reader._path, search_parent_directories=True)

        try:
            if since_tag:
                commits_raw = list(repo.iter_commits(f"{since_tag}..HEAD", max_count=200))
            elif since_date:
                commits_raw = list(repo.iter_commits("HEAD", max_count=500, after=since_date))
            else:
                cutoff = datetime.now() - timedelta(days=days)
                commits_raw = []
                for c in repo.iter_commits("HEAD", max_count=500):
                    if datetime.fromtimestamp(c.authored_date) < cutoff:
                        break
                    commits_raw.append(c)

            result = []
            for c in commits_raw[:100]:  # cap at 100
                result.append(CommitInfo(
                    sha=c.hexsha,
                    short_sha=c.hexsha[:7],
                    message=c.message.strip(),
                    author=c.author.name,
                    date=datetime.fromtimestamp(c.authored_date),
                    files_changed=[],
                ))
            return result
        except Exception:
            return []

    def _describe_period(self, days: int, since_tag: str, since_date: str) -> str:
        if since_tag:
            return f"since tag {since_tag}"
        if since_date:
            return f"since {since_date}"
        if days == 1:
            return "today"
        if days == 7:
            return "the past week"
        if days == 14:
            return "the past two weeks"
        return f"the past {days} days"
