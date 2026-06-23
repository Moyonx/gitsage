"""Prompt templates and builder functions for gitsage agents."""
from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

COMMIT_SYSTEM_PROMPT = """You are an expert software engineer helping to write clear, meaningful Git commit messages.

Your task is to analyse the provided diff and recent commit history, then generate 2-3 commit
message candidates that accurately describe the changes.

Guidelines:
- Use the Conventional Commits format: <type>(<scope>): <description>
- Types: feat, fix, refactor, docs, test, chore, perf, style, ci, build
- Keep the subject line under 72 characters
- Write in the imperative mood ("add feature" not "added feature")
- If a ticket/issue number can be inferred from the branch name (e.g. PROJ-123, #42), include it
- Follow any project-specific rules provided in CTX.md
- Rank candidates from most to least confident

Output ONLY valid JSON matching this schema — no prose, no markdown fences:
{schema}
"""

STANDUP_SYSTEM_PROMPT = """You are a professional engineering assistant that writes concise, impact-focused standup reports.

Your task is to summarise the provided Git commits into a standup update that a developer would
share with their team. Focus on what was accomplished and why it matters, not the raw commit list.

Guidelines:
- Write in the first person ("I implemented…", "I fixed…")
- Group related work into coherent themes
- Highlight blockers or notable decisions if present in the commits
- Be concise: aim for 3-5 bullet points
- Follow any project-specific rules provided in CTX.md

Output ONLY valid JSON matching this schema — no prose, no markdown fences:
{schema}
"""

PR_SYSTEM_PROMPT = """You are a senior engineer helping to write clear, comprehensive pull request descriptions.

Your task is to analyse the diff and commit history for a branch and produce a PR title and
description that help reviewers understand the change quickly.

Guidelines:
- The title should be concise (under 72 characters) and follow Conventional Commits style
- The description should explain *what* changed and *why*, not just restate the diff
- List any breaking changes explicitly
- Mention migration steps or config changes if applicable
- Use markdown formatting in the description (headers, bullet lists, code blocks as needed)

Output ONLY valid JSON matching this schema — no prose, no markdown fences:
{schema}
"""

EXPLAIN_SYSTEM_PROMPT = """You are a code archaeology agent. Your task is to investigate the history and context of code,
answering questions like "why does this exist?", "who changed this and when?", and
"what problem does this solve?".

Approach:
1. Systematically examine the provided git log, blame, and diff information
2. Identify the original author(s), the commit(s) that introduced the code, and the stated reason
3. Look for related issues, PR references, or ticket numbers in commit messages
4. If the code has been modified multiple times, trace the evolution
5. Cite your sources (commit hashes, file paths, line numbers) in the sources list
6. Be honest about uncertainty — prefer "medium" or "low" confidence when evidence is thin

Output ONLY valid JSON matching this schema — no prose, no markdown fences:
{schema}
"""

# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------

def get_json_schema_prompt(model_class: Type[BaseModel]) -> str:
    """Return the JSON schema for *model_class* as a formatted string.

    Used to embed schema information in prompts for non-Anthropic providers
    that do not support native structured output.
    """
    schema = model_class.model_json_schema()
    return json.dumps(schema, indent=2)


# ---------------------------------------------------------------------------
# User prompt builders
# ---------------------------------------------------------------------------

def build_commit_user_prompt(
    diff: str,
    recent_commits: list[str],
    branch_name: str,
    ctx_content: str,
    memory_content: str,
    skill_content: str,
) -> str:
    """Build the user-facing prompt for commit message generation."""
    parts: list[str] = []

    parts.append(f"## Branch\n{branch_name}")

    if recent_commits:
        formatted = "\n".join(f"  - {c}" for c in recent_commits[:10])
        parts.append(f"## Recent commits (for context)\n{formatted}")

    parts.append(f"## Diff\n```\n{diff}\n```")

    if ctx_content:
        parts.append(f"## Project context (CTX.md)\n{ctx_content}")

    if memory_content:
        parts.append(f"## Memory\n{memory_content}")

    if skill_content:
        parts.append(f"## Skill instructions\n{skill_content}")

    return "\n\n".join(parts)


def build_standup_user_prompt(
    commits: list[dict],
    date_str: str,
    ctx_content: str,
    memory_content: str,
    skill_content: str,
) -> str:
    """Build the user-facing prompt for standup report generation."""
    parts: list[str] = []

    parts.append(f"## Date\n{date_str}")

    if commits:
        commit_lines = []
        for c in commits:
            sha = c.get("sha", "")[:8]
            msg = c.get("message", "")
            author = c.get("author", "")
            ts = c.get("timestamp", "")
            commit_lines.append(f"  [{sha}] {msg} — {author} {ts}".strip())
        parts.append("## Commits\n" + "\n".join(commit_lines))
    else:
        parts.append("## Commits\nNo commits found for this period.")

    if ctx_content:
        parts.append(f"## Project context (CTX.md)\n{ctx_content}")

    if memory_content:
        parts.append(f"## Memory\n{memory_content}")

    if skill_content:
        parts.append(f"## Skill instructions\n{skill_content}")

    return "\n\n".join(parts)


def build_pr_user_prompt(
    diff: str,
    commit_messages: list[str],
    base_branch: str,
    head_branch: str,
    ctx_content: str,
) -> str:
    """Build the user-facing prompt for PR description generation."""
    parts: list[str] = []

    parts.append(f"## Branches\nBase: {base_branch}\nHead: {head_branch}")

    if commit_messages:
        formatted = "\n".join(f"  - {m}" for m in commit_messages)
        parts.append(f"## Commits on this branch\n{formatted}")

    parts.append(f"## Diff\n```\n{diff}\n```")

    if ctx_content:
        parts.append(f"## Project context (CTX.md)\n{ctx_content}")

    return "\n\n".join(parts)
