"""Explain agent - code archaeology using git history."""
from __future__ import annotations

from pathlib import Path

from ..config import LLMConfig
from ..context.blame import BlameContextBuilder
from .llm import BaseLLMClient, create_llm_client
from .models import ExplainOutput
from .prompts import EXPLAIN_SYSTEM_PROMPT, build_explain_user_prompt


class ExplainAgent:
    """Traces a file through git history and explains why the code exists."""

    def __init__(self, llm_client: BaseLLMClient, github_token: str = "") -> None:
        self._llm = llm_client
        self._github_token = github_token

    @classmethod
    def from_config(cls, llm_config: LLMConfig, github_token: str = "") -> "ExplainAgent":
        return cls(create_llm_client(llm_config), github_token)

    def explain(self, file_path: str, repo_path: Path = None) -> ExplainOutput:
        builder = BlameContextBuilder(
            repo_path=repo_path or Path.cwd(),
            github_token=self._github_token,
        )
        ctx = builder.build(file_path)

        user_prompt = build_explain_user_prompt(
            file_path=ctx.file_path,
            file_content=ctx.file_content,
            language=ctx.language,
            commits=ctx.commits,
            local_only=ctx.local_only,
        )

        output = self._llm.complete(
            system=EXPLAIN_SYSTEM_PROMPT,
            user=user_prompt,
            output_model=ExplainOutput,
        )
        output.local_only = ctx.local_only
        return output
