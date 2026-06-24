"""Explain agent — code archaeology using an iterative Agent loop.

The agent starts with file content and blame information, then
autonomously decides which additional data to fetch (commits, PRs,
Issues, related files) until it has enough context to explain why the
code exists.

Loop contract:
    - Max MAX_ITERATIONS iterations to prevent runaway costs
    - Each iteration the LLM returns an ExplainStep:
        * done=False  → fetch the requested tool and continue
        * done=True   → convert to ExplainOutput and return
    - On timeout/error → return best partial explanation at LOW confidence
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..config import LLMConfig
from ..context.blame import BlameContextBuilder, CommitDetail
from .llm import BaseLLMClient, LLMError, create_llm_client
from .models import ExplainOutput, ExplainStep

MAX_ITERATIONS = 8

# ---------------------------------------------------------------------------
# Agent system prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an expert software archaeologist performing code archaeology.

Your job: explain WHY a piece of code exists, using git blame history and any
additional context you choose to fetch.

You work in a loop. Each turn you receive the current context and must return
ONE of the following:

Option A — request more data (when context is insufficient):
  {
    "thinking": "I see this was changed in commit abc123, but I need the commit message to understand why.",
    "action": "get_commit",
    "params": {"sha": "abc123"},
    "done": false,
    "explanation": "", "confidence": "medium", "sources": []
  }

Option B — deliver final explanation (when you have enough):
  {
    "thinking": "Based on commit and PR context, I understand the full story.",
    "action": "done",
    "params": {},
    "done": true,
    "explanation": "This code exists because...",
    "confidence": "high",
    "sources": ["abc1234", "PR #89", "Issue #71"]
  }

Available actions:
  get_commit   params: {"sha": "8-char SHA"}              — full commit message + author
  get_pr       params: {"pr_number": 89}                  — PR title + description + linked issues
  get_issue    params: {"issue_number": 71}               — Issue title + body
  read_file    params: {"path": "relative/path.py"}       — read a related file (for context only)
  done         params: {}                                  — deliver final explanation

Guidelines:
- Use 'get_commit' first to understand context of key changes
- Use 'get_pr' when commit message contains PR number (e.g. #89)
- Use 'get_issue' when PR body mentions issue numbers
- Set confidence='high' only when you have PR/Issue context; 'medium' for commit-only
- Always cite your sources in the sources list
- Be concise but complete — explain the business reason, not just what the code does

Output ONLY valid JSON matching the schema. No prose, no markdown fences.
"""


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

class ToolExecutor:
    """Executes agent-requested tool calls and returns formatted results."""

    def __init__(
        self,
        builder: BlameContextBuilder,
        github_token: str = "",
        repo_path: Path = None,
    ) -> None:
        self._builder = builder
        self._github_token = github_token
        self._repo_path = repo_path or Path.cwd()
        self._pr_cache: dict[int, str] = {}
        self._issue_cache: dict[int, str] = {}

    def execute(self, action: str, params: dict) -> str:
        """Dispatch to the right tool and return a formatted string result."""
        try:
            if action == "get_commit":
                return self._get_commit(params.get("sha", ""))
            if action == "get_pr":
                return self._get_pr(int(params.get("pr_number", 0)))
            if action == "get_issue":
                return self._get_issue(int(params.get("issue_number", 0)))
            if action == "read_file":
                return self._read_file(params.get("path", ""))
            return f"[Unknown action: {action}]"
        except Exception as e:
            return f"[Tool error: {e}]"

    def _get_commit(self, sha: str) -> str:
        if not sha:
            return "[No SHA provided]"
        try:
            commit = self._builder._repo.commit(sha)
            return (
                f"Commit {sha[:8]}:\n"
                f"  Author: {commit.author.name}\n"
                f"  Date: {commit.authored_datetime.strftime('%Y-%m-%d')}\n"
                f"  Message: {commit.message.strip()[:500]}"
            )
        except Exception as e:
            return f"[Could not fetch commit {sha}: {e}]"

    def _get_pr(self, pr_number: int) -> str:
        if pr_number in self._pr_cache:
            return self._pr_cache[pr_number]
        if not self._github_token:
            return "[GitHub token required to fetch PR details]"
        try:
            import re
            import httpx
            remote = self._builder._repo.remotes[0].url if self._builder._repo.remotes else ""
            match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote)
            if not match:
                return "[Could not detect GitHub repo from remote URL]"
            repo_name = match.group(1)
            url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
            resp = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self._github_token}",
                         "Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            if resp.status_code != 200:
                return f"[GitHub API error {resp.status_code} fetching PR #{pr_number}]"
            data = resp.json()
            body = (data.get("body") or "")[:600]
            result = (
                f"PR #{pr_number}: {data.get('title', '')}\n"
                f"State: {data.get('state', '')}\n"
                f"Body: {body}"
            )
            self._pr_cache[pr_number] = result
            return result
        except Exception as e:
            return f"[Error fetching PR #{pr_number}: {e}]"

    def _get_issue(self, issue_number: int) -> str:
        if issue_number in self._issue_cache:
            return self._issue_cache[issue_number]
        if not self._github_token:
            return "[GitHub token required to fetch Issue details]"
        try:
            import re
            import httpx
            remote = self._builder._repo.remotes[0].url if self._builder._repo.remotes else ""
            match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote)
            if not match:
                return "[Could not detect GitHub repo from remote URL]"
            repo_name = match.group(1)
            url = f"https://api.github.com/repos/{repo_name}/issues/{issue_number}"
            resp = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self._github_token}",
                         "Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            if resp.status_code != 200:
                return f"[GitHub API error {resp.status_code} fetching Issue #{issue_number}]"
            data = resp.json()
            body = (data.get("body") or "")[:600]
            result = f"Issue #{issue_number}: {data.get('title', '')}\nBody: {body}"
            self._issue_cache[issue_number] = result
            return result
        except Exception as e:
            return f"[Error fetching Issue #{issue_number}: {e}]"

    def _read_file(self, path: str) -> str:
        if not path:
            return "[No path provided]"
        try:
            target = (self._repo_path / path).resolve()
            if not target.exists():
                return f"[File not found: {path}]"
            content = target.read_text(encoding="utf-8", errors="replace")
            # Limit to first 80 lines
            lines = content.splitlines()[:80]
            return "\n".join(lines) + ("\n... (truncated)" if len(content.splitlines()) > 80 else "")
        except Exception as e:
            return f"[Error reading {path}: {e}]"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ExplainAgent:
    """Iterative code archaeology agent — autonomously decides what to fetch."""

    def __init__(self, llm_client: BaseLLMClient, github_token: str = "") -> None:
        self._llm = llm_client
        self._github_token = github_token

    @classmethod
    def from_config(cls, llm_config: LLMConfig, github_token: str = "") -> "ExplainAgent":
        return cls(create_llm_client(llm_config), github_token)

    def explain(
        self,
        file_path: str,
        repo_path: Path = None,
        language_preamble: str = "",
    ) -> ExplainOutput:
        """Run the iterative Agent loop and return a final ExplainOutput."""
        root = repo_path or Path.cwd()
        builder = BlameContextBuilder(repo_path=root, github_token=self._github_token)

        # Build initial context
        ctx = builder.build(file_path)
        tool_exec = ToolExecutor(builder, github_token=self._github_token, repo_path=root)

        # Construct initial user message
        context_text = self._build_initial_context(ctx)
        conversation = context_text

        system = language_preamble + _SYSTEM

        # Agent loop
        for iteration in range(MAX_ITERATIONS):
            try:
                step: ExplainStep = self._llm.complete(
                    system=system,
                    user=conversation,
                    output_model=ExplainStep,
                )
            except LLMError as e:
                # Return partial result on LLM error
                return ExplainOutput(
                    explanation=f"(Analysis incomplete due to LLM error: {e})",
                    confidence="low",
                    sources=[],
                    local_only=ctx.local_only,
                )

            if step.done:
                return ExplainOutput(
                    explanation=step.explanation,
                    confidence=step.confidence,
                    sources=step.sources,
                    local_only=ctx.local_only,
                )

            # Execute the requested tool
            tool_result = tool_exec.execute(step.action, step.params)

            # Append to conversation context
            conversation += (
                f"\n\n---\n"
                f"[Iteration {iteration + 1}] Agent requested: {step.action}({step.params})\n"
                f"Tool result:\n{tool_result}\n"
                f"Agent thinking: {step.thinking}\n"
                f"---\n"
                f"Continue analysis based on the above. "
                f"Either request more data or deliver your final explanation."
            )

        # Max iterations reached — return best effort
        return ExplainOutput(
            explanation=(
                "Analysis reached maximum depth. "
                "Based on available information: the code appears to have been "
                "introduced in the commits listed in the blame history. "
                "Configure GITHUB_TOKEN for richer context."
            ),
            confidence="low",
            sources=[],
            local_only=ctx.local_only,
        )

    def _build_initial_context(self, ctx: object) -> str:
        """Format blame context as initial Agent prompt."""
        lines = [
            f"## File: {ctx.file_path} ({ctx.language})",
            "",
            "### Content (excerpt)",
            "```",
            ctx.file_content[:2000],
            "```" if len(ctx.file_content) <= 2000 else "```\n... (truncated)",
            "",
            "### Git Blame Summary",
        ]

        for commit in ctx.commits[:8]:
            lines.append(
                f"- Commit {commit.short_sha} by {commit.author} "
                f"({commit.date.strftime('%Y-%m-%d')}): "
                f"{commit.message.splitlines()[0][:100]}"
            )
            if commit.pr_number:
                lines.append(f"  → Associated PR: #{commit.pr_number}")
            if commit.issue_numbers:
                lines.append(f"  → Linked issues: {', '.join(f'#{n}' for n in commit.issue_numbers)}")

        lines += [
            "",
            "### Instructions",
            "Analyse the above and decide what additional context you need.",
            "Use the available tools to fetch commit details, PR descriptions,",
            "or related files. When you have enough context, set done=true.",
        ]

        return "\n".join(lines)
