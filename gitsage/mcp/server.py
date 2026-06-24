"""MCP Server for gitsage - exposes git state and AI generation as tools."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

# Use the mcp package (already in pyproject.toml dependencies)
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

from ..context.git_reader import GitReader


def _git_reader() -> GitReader:
    return GitReader(Path.cwd())


def create_server() -> "Server":
    """Create and configure the gitsage MCP server."""
    if not MCP_AVAILABLE:
        raise ImportError("mcp package not installed. Run: pip install mcp")

    server = Server("gitsage")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_staged_diff",
                description="Get the current staged diff (changes ready to commit). Returns the raw diff text.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="get_recent_commits",
                description="Get recent commits from the repository.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of commits to return (default 10, max 50)",
                            "default": 10,
                        }
                    },
                    "required": [],
                },
            ),
            Tool(
                name="get_git_status",
                description="Get the current git repository status: branch name, staged files, whether working tree is clean.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="get_branch_info",
                description="Get current branch name and the last commit on it.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="get_file_history",
                description="Get git commit history for a specific file.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file (relative to repo root)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of commits to return (default 10)",
                            "default": 10,
                        },
                    },
                    "required": ["file_path"],
                },
            ),
            Tool(
                name="generate_commit_message",
                description=(
                    "Generate AI-powered commit message candidates for currently staged changes. "
                    "Respects project CTX.md conventions, user memory, and style preferences. "
                    "Returns 2-3 ranked candidates with confidence scores. "
                    "Requires staged files (git add) and a configured LLM."
                ),
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="generate_standup",
                description=(
                    "Generate an AI-powered standup report from today's commits. "
                    "Respects project CTX.md conventions and user style preferences. "
                    "Returns structured content ready to share with your team."
                ),
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            path = Path.cwd()
            if name == "generate_commit_message":
                result = await asyncio.to_thread(_generate_commit_message, path, arguments)
            elif name == "generate_standup":
                result = await asyncio.to_thread(_generate_standup, path, arguments)
            else:
                git = _git_reader()
                result = _dispatch(git, name, arguments)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    return server


def _dispatch(git: GitReader, name: str, args: dict) -> Any:
    if name == "get_staged_diff":
        diff = git.get_staged_diff()
        return {"diff": diff, "empty": not diff.strip()}

    elif name == "get_recent_commits":
        limit = min(int(args.get("limit", 10)), 50)
        commits = git.get_recent_commits(limit=limit)
        return {
            "commits": [
                {
                    "sha": c.short_sha,
                    "author": c.author,
                    "date": c.date.isoformat(),
                    "message": c.message,
                }
                for c in commits
            ]
        }

    elif name == "get_git_status":
        state = git.get_state(commit_limit=1)
        return {
            "branch": state.branch_name,
            "repo": state.repo_name,
            "is_clean": state.is_clean,
            "staged_files": state.staged_files,
            "staged_summary": state.staged_summary,
        }

    elif name == "get_branch_info":
        state = git.get_state(commit_limit=1)
        last = state.recent_commits[0] if state.recent_commits else None
        return {
            "branch": state.branch_name,
            "last_commit": {
                "sha": last.short_sha,
                "message": last.message,
                "author": last.author,
                "date": last.date.isoformat(),
            } if last else None,
        }

    elif name == "get_file_history":
        file_path = args.get("file_path", "")
        limit = min(int(args.get("limit", 10)), 50)
        commits = git.get_file_log(file_path, limit=limit)
        return {
            "file": file_path,
            "commits": [
                {
                    "sha": c.short_sha,
                    "author": c.author,
                    "date": c.date.isoformat(),
                    "message": c.message,
                }
                for c in commits
            ],
        }

    else:
        return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# LLM generation helpers (synchronous — called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _generate_commit_message(path: Path, args: dict) -> dict:  # noqa: ARG001
    """Generate commit message candidates for staged changes.

    Reuses the full gitsage commit pipeline: context assembly, LLM call,
    quality gate, and deterministic override.
    """
    from ..config import load_config
    from ..context import ContextBuilder
    from ..agent import create_llm_client, build_commit_user_prompt, CommitOutput
    from ..agent.prompts import COMMIT_SYSTEM_PROMPT
    from ..harness import QualityGate, DeterministicOverride
    from ..preferences import load_preferences

    cfg = load_config()
    builder = ContextBuilder(path)
    ctx = builder.build_commit_context()

    if ctx.git_state.is_clean:
        return {"error": "No staged changes found. Stage files with 'git add' first."}

    recent_msgs = [c.message for c in ctx.git_state.recent_commits]
    user_prompt = build_commit_user_prompt(
        diff=ctx.git_state.staged_diff,
        recent_commits=recent_msgs,
        branch_name=ctx.git_state.branch_name,
        ctx_content=ctx.ctx.raw,
        memory_content=ctx.memory_content,
        skill_content="",
    )

    prefs = load_preferences()
    pref_hint = prefs.to_prompt_hint()
    system = (
        prefs.language_preamble
        + COMMIT_SYSTEM_PROMPT
        + (f"\n\n## Style Preferences\n{pref_hint}" if pref_hint else "")
    )

    llm = create_llm_client(cfg.llm)
    output: CommitOutput = llm.complete(system=system, user=user_prompt, output_model=CommitOutput)

    gate = QualityGate.for_commit()
    override = DeterministicOverride(cfg.rules, branch_name=ctx.git_state.branch_name)

    candidates = []
    for c in output.candidates:
        gate.check(c.message)
        c.message = override.apply_to_commit(c.message)
        candidates.append({
            "message": c.message,
            "confidence": c.confidence,
            "reason": c.reason,
        })

    result: dict[str, Any] = {
        "candidates": candidates,
        "staged_files": ctx.git_state.staged_files,
        "branch": ctx.git_state.branch_name,
    }
    if output.warning:
        result["warning"] = output.warning
    return result


def _generate_standup(path: Path, args: dict) -> dict:  # noqa: ARG001
    """Generate a standup report from today's commits.

    Reuses the full gitsage standup pipeline: context assembly, LLM call,
    and user style preferences.
    """
    from ..config import load_config
    from ..context import ContextBuilder
    from ..agent import create_llm_client, build_standup_user_prompt, StandupOutput
    from ..agent.prompts import STANDUP_SYSTEM_PROMPT
    from ..preferences import load_preferences

    cfg = load_config()
    builder = ContextBuilder(path)
    ctx = builder.build_standup_context()

    commits_data = [
        {
            "sha": c.sha,
            "message": c.message,
            "author": c.author,
            "timestamp": c.date.strftime("%H:%M"),
        }
        for c in ctx.git_state.today_commits
    ]

    user_prompt = build_standup_user_prompt(
        commits=commits_data,
        date_str=ctx.date_str,
        ctx_content=ctx.ctx.raw,
        memory_content=ctx.memory_content,
        skill_content="",
    )

    prefs = load_preferences()
    pref_hint = prefs.to_prompt_hint()
    system = (
        prefs.language_preamble
        + STANDUP_SYSTEM_PROMPT
        + (f"\n\n## Style Preferences\n{pref_hint}" if pref_hint else "")
    )

    llm = create_llm_client(cfg.llm)
    output: StandupOutput = llm.complete(system=system, user=user_prompt, output_model=StandupOutput)

    return {
        "content": output.content,
        "commit_count": len(commits_data),
        "date": ctx.date_str,
    }


async def run_server() -> None:
    """Run the MCP server on stdio transport."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
