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
        from gitsage.mcp.server import _dispatch, create_server, _generate_commit_message, _generate_standup
        assert callable(_dispatch)
        assert callable(_generate_commit_message)
        assert callable(_generate_standup)


# ---------------------------------------------------------------------------
# Helpers for generation tool tests
# ---------------------------------------------------------------------------

def _mock_commit_context(is_clean: bool = False):
    """Build a minimal mock CommitContext."""
    from datetime import datetime
    from gitsage.context.git_reader import CommitInfo

    mock_ctx = MagicMock()
    mock_ctx.git_state.is_clean = is_clean
    mock_ctx.git_state.staged_diff = "+def foo(): pass"
    mock_ctx.git_state.staged_files = ["src/foo.py"]
    mock_ctx.git_state.branch_name = "feature/PROJ-42"
    mock_ctx.git_state.recent_commits = [
        CommitInfo(
            sha="abc1234def", short_sha="abc1234",
            message="feat: previous commit",
            author="Dev", date=datetime(2024, 1, 15),
            files_changed=[],
        )
    ]
    mock_ctx.ctx.raw = ""
    mock_ctx.memory_content = ""
    mock_ctx.skill_content = ""
    return mock_ctx


def _mock_standup_context():
    """Build a minimal mock StandupContext."""
    from datetime import datetime

    mock_ctx = MagicMock()
    mock_ctx.git_state.today_commits = [
        MagicMock(
            sha="abc1234def",
            message="feat: add thing",
            author="Dev",
            date=MagicMock(strftime=lambda fmt: "10:30"),
        )
    ]
    mock_ctx.ctx.raw = ""
    mock_ctx.memory_content = ""
    mock_ctx.skill_content = ""
    mock_ctx.date_str = "2024-01-15"
    return mock_ctx


def _mock_llm_for_commit():
    """Build a mock LLM that returns a valid CommitOutput."""
    from gitsage.agent.models import CommitOutput, CommitCandidate
    mock_llm = MagicMock()
    mock_llm.complete.return_value = CommitOutput(
        candidates=[
            CommitCandidate(message="feat(foo): add foo function", confidence="high", reason="clear intent"),
            CommitCandidate(message="feat: add foo", confidence="medium", reason="shorter form"),
        ]
    )
    return mock_llm


def _mock_llm_for_standup():
    """Build a mock LLM that returns a valid StandupOutput."""
    from gitsage.agent.models import StandupOutput
    mock_llm = MagicMock()
    mock_llm.complete.return_value = StandupOutput(content="- Added foo function to src/foo.py")
    return mock_llm


# ---------------------------------------------------------------------------
# Tests for _generate_commit_message
# ---------------------------------------------------------------------------

class TestGenerateCommitMessage:
    _PATCHES = [
        "gitsage.config.load_config",
        "gitsage.context.ContextBuilder",
        "gitsage.agent.create_llm_client",
        "gitsage.harness.QualityGate",
        "gitsage.harness.DeterministicOverride",
        "gitsage.preferences.load_preferences",
    ]

    def _run(self, path, args, *, is_clean=False):
        """Helper: call _generate_commit_message with all dependencies mocked."""
        from pathlib import Path
        from gitsage.mcp.server import _generate_commit_message
        from gitsage.preferences import UserPreferences

        mock_cfg = MagicMock()
        mock_ctx = _mock_commit_context(is_clean=is_clean)
        mock_llm = _mock_llm_for_commit()
        mock_builder = MagicMock()
        mock_builder.build_commit_context.return_value = mock_ctx
        mock_gate = MagicMock()
        mock_gate.check.return_value = MagicMock(passed=True)
        mock_override = MagicMock()
        mock_override.apply_to_commit.side_effect = lambda m: m  # identity

        with patch("gitsage.config.load_config", return_value=mock_cfg), \
             patch("gitsage.context.ContextBuilder", return_value=mock_builder), \
             patch("gitsage.agent.create_llm_client", return_value=mock_llm), \
             patch("gitsage.harness.QualityGate") as MockGate, \
             patch("gitsage.harness.DeterministicOverride", return_value=mock_override), \
             patch("gitsage.preferences.load_preferences", return_value=UserPreferences()):
            MockGate.for_commit.return_value = mock_gate
            return _generate_commit_message(path or Path("/tmp"), args)

    def test_returns_candidates(self, tmp_path):
        result = self._run(tmp_path, {})
        assert "candidates" in result
        assert len(result["candidates"]) == 2
        assert result["candidates"][0]["message"] == "feat(foo): add foo function"
        assert result["candidates"][0]["confidence"] == "high"

    def test_returns_branch_and_staged_files(self, tmp_path):
        result = self._run(tmp_path, {})
        assert result["branch"] == "feature/PROJ-42"
        assert "src/foo.py" in result["staged_files"]

    def test_no_warning_when_none(self, tmp_path):
        result = self._run(tmp_path, {})
        assert "warning" not in result

    def test_error_when_no_staged_changes(self, tmp_path):
        result = self._run(tmp_path, {}, is_clean=True)
        assert "error" in result
        assert "staged" in result["error"].lower()

    def test_override_applied_to_each_candidate(self, tmp_path):
        """DeterministicOverride.apply_to_commit must be called for every candidate."""
        from pathlib import Path
        from gitsage.mcp.server import _generate_commit_message
        from gitsage.preferences import UserPreferences

        mock_cfg = MagicMock()
        mock_ctx = _mock_commit_context()
        mock_llm = _mock_llm_for_commit()
        mock_builder = MagicMock()
        mock_builder.build_commit_context.return_value = mock_ctx
        mock_gate = MagicMock()
        mock_gate.check.return_value = MagicMock(passed=True)
        mock_override = MagicMock()
        mock_override.apply_to_commit.side_effect = lambda m: m + " [PROJ-42]"

        with patch("gitsage.config.load_config", return_value=mock_cfg), \
             patch("gitsage.context.ContextBuilder", return_value=mock_builder), \
             patch("gitsage.agent.create_llm_client", return_value=mock_llm), \
             patch("gitsage.harness.QualityGate") as MockGate, \
             patch("gitsage.harness.DeterministicOverride", return_value=mock_override), \
             patch("gitsage.preferences.load_preferences", return_value=UserPreferences()):
            MockGate.for_commit.return_value = mock_gate
            result = _generate_commit_message(Path("/tmp"), {})

        assert mock_override.apply_to_commit.call_count == 2
        assert result["candidates"][0]["message"].endswith("[PROJ-42]")


# ---------------------------------------------------------------------------
# Tests for _generate_standup
# ---------------------------------------------------------------------------

class TestGenerateStandup:
    def _run(self, path, args):
        from pathlib import Path
        from gitsage.mcp.server import _generate_standup
        from gitsage.preferences import UserPreferences

        mock_cfg = MagicMock()
        mock_ctx = _mock_standup_context()
        mock_llm = _mock_llm_for_standup()
        mock_builder = MagicMock()
        mock_builder.build_standup_context.return_value = mock_ctx

        with patch("gitsage.config.load_config", return_value=mock_cfg), \
             patch("gitsage.context.ContextBuilder", return_value=mock_builder), \
             patch("gitsage.agent.create_llm_client", return_value=mock_llm), \
             patch("gitsage.preferences.load_preferences", return_value=UserPreferences()):
            return _generate_standup(path or Path("/tmp"), args)

    def test_returns_content(self, tmp_path):
        result = self._run(tmp_path, {})
        assert "content" in result
        assert "foo function" in result["content"]

    def test_returns_commit_count_and_date(self, tmp_path):
        result = self._run(tmp_path, {})
        assert result["commit_count"] == 1
        assert result["date"] == "2024-01-15"

    def test_empty_commits_still_works(self, tmp_path):
        """Standup should work even with no commits today."""
        from pathlib import Path
        from gitsage.mcp.server import _generate_standup
        from gitsage.preferences import UserPreferences

        mock_cfg = MagicMock()
        mock_ctx = _mock_standup_context()
        mock_ctx.git_state.today_commits = []  # no commits
        mock_llm = _mock_llm_for_standup()
        mock_builder = MagicMock()
        mock_builder.build_standup_context.return_value = mock_ctx

        with patch("gitsage.config.load_config", return_value=mock_cfg), \
             patch("gitsage.context.ContextBuilder", return_value=mock_builder), \
             patch("gitsage.agent.create_llm_client", return_value=mock_llm), \
             patch("gitsage.preferences.load_preferences", return_value=UserPreferences()):
            result = _generate_standup(Path("/tmp"), {})

        assert result["commit_count"] == 0
        assert "content" in result
