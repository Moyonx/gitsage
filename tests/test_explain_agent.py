"""Tests for the iterative ExplainAgent loop."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gitsage.agent.models import ExplainOutput, ExplainStep


# ---------------------------------------------------------------------------
# ExplainStep model validation
# ---------------------------------------------------------------------------

class TestExplainStepModel:
    def test_done_step_is_valid(self):
        step = ExplainStep(
            thinking="I have enough context.",
            action="done",
            params={},
            done=True,
            explanation="This code exists because of compliance requirement.",
            confidence="high",
            sources=["abc1234", "PR #89"],
        )
        assert step.done is True
        assert step.action == "done"
        assert step.confidence == "high"

    def test_intermediate_step_get_commit(self):
        step = ExplainStep(
            thinking="Need to check this commit.",
            action="get_commit",
            params={"sha": "abc12345"},
            done=False,
        )
        assert step.done is False
        assert step.action == "get_commit"
        assert step.params["sha"] == "abc12345"

    def test_intermediate_step_get_pr(self):
        step = ExplainStep(
            thinking="Found PR #42.",
            action="get_pr",
            params={"pr_number": 42},
            done=False,
        )
        assert step.action == "get_pr"

    def test_default_explanation_empty_when_not_done(self):
        step = ExplainStep(
            thinking="Still working.", action="get_commit", params={}, done=False
        )
        assert step.explanation == ""
        assert step.sources == []


# ---------------------------------------------------------------------------
# ToolExecutor tests
# ---------------------------------------------------------------------------

class TestToolExecutor:
    def _make_executor(self, repo_path=None):
        from gitsage.agent.explain_agent import ToolExecutor
        mock_builder = MagicMock()  # no spec so _repo attribute is accessible
        # Mock a repo with a single commit
        mock_commit = MagicMock()
        mock_commit.author.name = "Alice"
        mock_commit.authored_datetime.strftime.return_value = "2024-01-15"
        mock_commit.message = "feat: add retry logic"
        mock_builder._repo.commit.return_value = mock_commit
        mock_builder._repo.remotes = []
        return ToolExecutor(mock_builder, github_token="", repo_path=repo_path or Path("/tmp"))

    def test_get_commit_returns_formatted_result(self):
        executor = self._make_executor()
        result = executor.execute("get_commit", {"sha": "abc12345"})
        assert "abc12345" in result or "abc1234" in result
        assert "Alice" in result
        assert "feat: add retry logic" in result

    def test_get_pr_without_token_returns_hint(self):
        executor = self._make_executor()
        result = executor.execute("get_pr", {"pr_number": 42})
        assert "token" in result.lower()

    def test_get_issue_without_token_returns_hint(self):
        executor = self._make_executor()
        result = executor.execute("get_issue", {"issue_number": 10})
        assert "token" in result.lower()

    def test_unknown_action_returns_error(self):
        executor = self._make_executor()
        result = executor.execute("unknown_action", {})
        assert "Unknown" in result

    def test_read_file_returns_content(self, tmp_path):
        target = tmp_path / "hello.py"
        target.write_text("def greet():\n    return 'hello'\n")
        executor = self._make_executor(repo_path=tmp_path)
        result = executor.execute("read_file", {"path": "hello.py"})
        assert "def greet" in result

    def test_read_file_missing_returns_error(self, tmp_path):
        executor = self._make_executor(repo_path=tmp_path)
        result = executor.execute("read_file", {"path": "nonexistent.py"})
        assert "not found" in result.lower() or "error" in result.lower()

    def test_read_file_no_path_returns_error(self, tmp_path):
        executor = self._make_executor(repo_path=tmp_path)
        result = executor.execute("read_file", {})
        assert "No path" in result


# ---------------------------------------------------------------------------
# ExplainAgent loop tests
# ---------------------------------------------------------------------------

class TestExplainAgentLoop:

    def _make_mock_context(self):
        """Create a minimal BlameContext-like object."""
        ctx = MagicMock()
        ctx.file_path = "src/auth.py"
        ctx.file_content = "def validate(token):\n    return jwt.decode(token)\n"
        ctx.language = "Python"
        ctx.local_only = True
        ctx.commits = [
            MagicMock(
                short_sha="abc1234",
                author="Alice",
                date=MagicMock(strftime=lambda f: "2024-01-15"),
                message="fix: handle token expiry",
                pr_number=None,
                issue_numbers=[],
            )
        ]
        return ctx

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    def test_agent_stops_when_done_immediately(self, mock_llm):
        """Agent returns immediately if first step is done=True."""
        from gitsage.agent.explain_agent import ExplainAgent

        mock_llm.complete.return_value = ExplainStep(
            thinking="Enough info from blame.",
            action="done",
            params={},
            done=True,
            explanation="This code validates JWT tokens.",
            confidence="medium",
            sources=["abc1234"],
        )

        agent = ExplainAgent(mock_llm, github_token="")
        ctx = self._make_mock_context()

        with patch("gitsage.agent.explain_agent.BlameContextBuilder") as MockBuilder:
            MockBuilder.return_value.build.return_value = ctx
            with patch("gitsage.agent.explain_agent.ToolExecutor"):
                result = agent.explain("src/auth.py")

        assert isinstance(result, ExplainOutput)
        assert result.explanation == "This code validates JWT tokens."
        assert result.confidence == "medium"
        mock_llm.complete.assert_called_once()

    def test_agent_fetches_commit_then_done(self, mock_llm):
        """Agent makes one tool call before delivering explanation."""
        from gitsage.agent.explain_agent import ExplainAgent

        mock_llm.complete.side_effect = [
            # First call: request commit details
            ExplainStep(
                thinking="Need commit details.",
                action="get_commit",
                params={"sha": "abc1234"},
                done=False,
            ),
            # Second call: done
            ExplainStep(
                thinking="Now I understand.",
                action="done",
                params={},
                done=True,
                explanation="Introduced to fix token expiry bug.",
                confidence="high",
                sources=["abc1234"],
            ),
        ]

        agent = ExplainAgent(mock_llm, github_token="")
        ctx = self._make_mock_context()

        with patch("gitsage.agent.explain_agent.BlameContextBuilder") as MockBuilder:
            MockBuilder.return_value.build.return_value = ctx
            with patch("gitsage.agent.explain_agent.ToolExecutor") as MockExec:
                MockExec.return_value.execute.return_value = "Commit info: fix token expiry"
                result = agent.explain("src/auth.py")

        assert result.explanation == "Introduced to fix token expiry bug."
        assert result.confidence == "high"
        assert mock_llm.complete.call_count == 2

    def test_agent_returns_low_confidence_at_max_iterations(self, mock_llm):
        """After MAX_ITERATIONS, agent returns a fallback result."""
        from gitsage.agent.explain_agent import ExplainAgent, MAX_ITERATIONS

        # Always requests more data, never done
        mock_llm.complete.return_value = ExplainStep(
            thinking="Need more.",
            action="get_commit",
            params={"sha": "abc1234"},
            done=False,
        )

        agent = ExplainAgent(mock_llm, github_token="")
        ctx = self._make_mock_context()

        with patch("gitsage.agent.explain_agent.BlameContextBuilder") as MockBuilder:
            MockBuilder.return_value.build.return_value = ctx
            with patch("gitsage.agent.explain_agent.ToolExecutor") as MockExec:
                MockExec.return_value.execute.return_value = "Some commit info"
                result = agent.explain("src/auth.py")

        assert result.confidence == "low"
        assert mock_llm.complete.call_count == MAX_ITERATIONS

    def test_agent_handles_llm_error_gracefully(self, mock_llm):
        """LLM errors return a low-confidence fallback without crashing."""
        from gitsage.agent.explain_agent import ExplainAgent
        from gitsage.agent.llm import LLMError

        mock_llm.complete.side_effect = LLMError("rate limit")

        agent = ExplainAgent(mock_llm, github_token="")
        ctx = self._make_mock_context()

        with patch("gitsage.agent.explain_agent.BlameContextBuilder") as MockBuilder:
            MockBuilder.return_value.build.return_value = ctx
            with patch("gitsage.agent.explain_agent.ToolExecutor"):
                result = agent.explain("src/auth.py")

        assert result.confidence == "low"
        assert "error" in result.explanation.lower() or "incomplete" in result.explanation.lower()

    def test_language_preamble_prepended_to_system(self, mock_llm):
        """language_preamble is prepended to the system prompt."""
        from gitsage.agent.explain_agent import ExplainAgent

        mock_llm.complete.return_value = ExplainStep(
            thinking="done", action="done", params={}, done=True,
            explanation="ok", confidence="high", sources=[],
        )

        agent = ExplainAgent(mock_llm, github_token="")
        ctx = self._make_mock_context()

        with patch("gitsage.agent.explain_agent.BlameContextBuilder") as MockBuilder:
            MockBuilder.return_value.build.return_value = ctx
            with patch("gitsage.agent.explain_agent.ToolExecutor"):
                agent.explain("src/auth.py", language_preamble="LANGUAGE: zh\n")

        call_kwargs = mock_llm.complete.call_args
        system_used = call_kwargs[1].get("system") or call_kwargs[0][0]
        assert system_used.startswith("LANGUAGE: zh")
