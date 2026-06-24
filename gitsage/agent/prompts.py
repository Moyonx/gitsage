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

CATCHUP_SYSTEM_PROMPT = """
You are a developer workflow assistant summarizing recent repository changes.
Given a list of commits over a time period, produce a clear summary of:
- What significant work happened
- Key highlights worth calling out
- The overall theme or direction of changes

Focus on user-facing or architecturally important changes.
Skip pure chore/dependency/formatting commits unless significant.
Output JSON matching CatchupOutput schema.
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


def build_explain_user_prompt(
    file_path: str,
    file_content: str,
    language: str,
    commits: list,  # list[CommitDetail]
    local_only: bool,
) -> str:
    """Build the user-facing prompt for code archaeology / explain generation."""
    commit_sections = []
    for c in commits:
        section = f"Commit {c.short_sha} by {c.author} on {c.date.strftime('%Y-%m-%d')}:\n"
        section += f"  Message: {c.message[:200]}\n"
        if c.pr_number:
            section += f"  PR #{c.pr_number}: {c.pr_title or '(no title)'}\n"
            if c.pr_body:
                section += f"  PR Description: {c.pr_body[:400]}\n"
        for i, (title, body) in enumerate(zip(c.issue_titles, c.issue_bodies)):
            section += f"  Issue #{c.issue_numbers[i]}: {title}\n"
            if body:
                section += f"    {body[:300]}\n"
        commit_sections.append(section)

    context_note = (
        "(Note: No GitHub token configured — analysis based on local git history only.)"
        if local_only else ""
    )

    return f"""File: {file_path} ({language})

{context_note}

=== File Content (excerpt) ===
{file_content[:3000]}

=== Git History for This File ===
{chr(10).join(commit_sections)}

Based on the above, explain why this code exists and how it came to be written this way.
Be specific, cite commit SHAs and PR/Issue numbers where relevant.
"""


def build_catchup_user_prompt(
    commits: list,
    period_description: str,
    repo_name: str,
    ctx_content: str = "",
) -> str:
    """Build the user-facing prompt for catchup summary generation."""
    commit_lines = []
    for c in commits:
        msg = c.message if hasattr(c, "message") else c.get("message", "")
        author = c.author if hasattr(c, "author") else c.get("author", "")
        date = c.date.strftime("%Y-%m-%d") if hasattr(c, "date") and hasattr(c.date, "strftime") else str(getattr(c, "date", c.get("date", "")))[:10]
        sha = c.short_sha if hasattr(c, "short_sha") else c.get("sha", "")[:7]
        commit_lines.append(f"- [{sha}] {date} {author}: {msg[:120]}")

    commits_text = "\n".join(commit_lines) if commit_lines else "(no commits)"
    ctx_section = f"\nProject context:\n{ctx_content[:800]}" if ctx_content else ""

    return f"""Repository: {repo_name}
Period: {period_description}
Total commits: {len(commits)}{ctx_section}

Commits:
{commits_text}

Summarize what happened in this period. Focus on significant changes.
"""


# ---------------------------------------------------------------------------
# config init prompts
# ---------------------------------------------------------------------------

CONFIG_INIT_SYSTEM_PROMPT = """You are an expert developer tooling assistant helping to generate a CTX.md
project context file for gitsage.

CTX.md is read by gitsage before every command to personalise its AI output.
It should capture:
- What the project does (briefly)
- Commit message conventions detected from git history
- Standup format/audience
- Deterministic rules (always/never)

Keep the file concise (under 60 lines). Do NOT invent information not supported
by the commit history provided. Write in the same language as the project's commits.
Output ONLY the CTX.md content — no explanation, no markdown fences.
"""


def build_config_init_prompt(
    repo_name: str,
    patterns: dict,
) -> str:
    """Build the user prompt for intelligent CTX.md generation."""
    lang = patterns.get("language", "en")
    uses_emoji = patterns.get("uses_emoji", False)
    uses_type = patterns.get("uses_type", False)
    uses_scope = patterns.get("uses_scope", False)
    avg_len = patterns.get("avg_length", 50)
    top_scopes = patterns.get("top_scopes", [])
    top_types = patterns.get("top_types", [])
    sample_msgs = patterns.get("sample_msgs", [])
    total = patterns.get("total_analyzed", 0)

    sample_block = "\n".join(f"  - {m}" for m in sample_msgs) if sample_msgs else "  (none)"

    return f"""Generate a CTX.md file for repository: {repo_name}

Analysis of the last {total} commits:
- Language: {lang} ({"Chinese/中文" if lang == "zh" else "English" if lang == "en" else "mixed"})
- Uses emoji: {"yes" if uses_emoji else "no"}
- Uses Conventional Commits type prefix (feat/fix/etc): {"yes" if uses_type else "no"}
- Uses scope (feat(module): ...): {"yes" if uses_scope else "no"}
- Average commit message length: {avg_len} chars
- Most common scopes/modules: {", ".join(top_scopes) if top_scopes else "none detected"}
- Most common types: {", ".join(top_types) if top_types else "none detected"}

Sample commit messages:
{sample_block}

Generate a CTX.md that:
1. Has a short ## Project Background section (leave a placeholder note for the user to fill in project description)
2. Has a ## Commit Rules section reflecting the DETECTED style above (with a concrete example)
3. Has a ## Standup Format section with sensible defaults
4. Has a ## Rules section with always/never rules derived from the patterns
5. Uses the same language as the detected commit language

Output ONLY the CTX.md content.
"""
