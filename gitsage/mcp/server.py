"""MCP Server for gitsage - exposes git state as tools."""
from __future__ import annotations

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
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
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


async def run_server() -> None:
    """Run the MCP server on stdio transport."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
