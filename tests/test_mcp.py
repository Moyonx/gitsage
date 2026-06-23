"""Tests for MCP server."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


class TestMcpDispatch:
    """Test the _dispatch function with mocked git reader."""

    def _make_git_reader(self):
        from datetime import datetime
        from gitsage.context.git_reader import GitState, CommitInfo
        mock = MagicMock()
        mock.get_staged_diff.return_value = "+def new_func():\n+    pass"
        mock.get_recent_commits.return_value = [
            CommitInfo(
                sha="abc1234def", short_sha="abc1234",
                message="feat: add feature",
                author="Alice", date=datetime(2024, 1, 15),
                files_changed=["src/main.py"],
            )
        ]
        mock.get_state.return_value = GitState(
            repo_path=__import__('pathlib').Path("/tmp"),
            repo_name="owner/repo",
            branch_name="main",
            staged_diff="+def new_func():\n+    pass",
            staged_files=["src/main.py"],
            staged_summary="1 file changed, +2/-0",
            recent_commits=[],
            today_commits=[],
            is_clean=False,
        )
        mock.get_file_log.return_value = []
        return mock

    def test_get_staged_diff(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        result = _dispatch(mock_git, "get_staged_diff", {})
        assert "diff" in result
        assert result["diff"] == "+def new_func():\n+    pass"

    def test_get_staged_diff_empty(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        mock_git.get_staged_diff.return_value = ""
        result = _dispatch(mock_git, "get_staged_diff", {})
        assert result["empty"] is True

    def test_get_recent_commits(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        result = _dispatch(mock_git, "get_recent_commits", {"limit": 5})
        assert "commits" in result
        assert len(result["commits"]) == 1
        assert result["commits"][0]["sha"] == "abc1234"

    def test_get_recent_commits_caps_at_50(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        mock_git.get_recent_commits.return_value = []
        _dispatch(mock_git, "get_recent_commits", {"limit": 9999})
        # Should have been called with limit capped at 50
        mock_git.get_recent_commits.assert_called_with(limit=50)

    def test_get_git_status(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        result = _dispatch(mock_git, "get_git_status", {})
        assert result["branch"] == "main"
        assert result["repo"] == "owner/repo"
        assert result["is_clean"] is False

    def test_get_branch_info(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        result = _dispatch(mock_git, "get_branch_info", {})
        assert result["branch"] == "main"

    def test_get_file_history(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        result = _dispatch(mock_git, "get_file_history", {"file_path": "src/main.py"})
        assert "file" in result
        assert result["file"] == "src/main.py"

    def test_unknown_tool_returns_error(self):
        from gitsage.mcp.server import _dispatch
        mock_git = self._make_git_reader()
        result = _dispatch(mock_git, "nonexistent_tool", {})
        assert "error" in result


class TestMcpAvailability:
    def test_mcp_available_flag(self):
        from gitsage.mcp import MCP_AVAILABLE
        # Should be either True or False, not raise
        assert isinstance(MCP_AVAILABLE, bool)

    def test_mcp_server_import(self):
        # Should import without error
        from gitsage.mcp.server import _dispatch, create_server
        assert callable(_dispatch)
