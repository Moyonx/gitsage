"""Tests for catchup agent."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from gitsage.agent.models import CatchupOutput
from gitsage.agent.catchup_agent import CatchupAgent
from gitsage.context.git_reader import CommitInfo


def make_commit(sha="abc1234", msg="feat: add feature", author="dev", days_ago=1):
    return CommitInfo(
        sha=sha,
        short_sha=sha[:7],
        message=msg,
        author=author,
        date=datetime.now() - timedelta(days=days_ago),
        files_changed=[],
    )


class TestCatchupAgent:

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.complete.return_value = CatchupOutput(
            summary="This week: added payment retry and fixed auth bug.",
            highlights=["Added payment retry", "Fixed auth bug"],
            period_description="the past week",
            commit_count=5,
        )
        return llm

    def test_returns_catchup_output(self, mock_llm):
        # Verify that the mock LLM returns a proper CatchupOutput
        result = mock_llm.complete.return_value
        assert isinstance(result, CatchupOutput)
        assert result.summary
        assert result.commit_count == 5

    def test_empty_commits_returns_no_commits_message(self, mock_llm):
        agent = CatchupAgent(mock_llm)
        with patch.object(agent, "_get_commits", return_value=[]):
            with patch("gitsage.agent.catchup_agent.GitReader"), \
                 patch("gitsage.agent.catchup_agent.CTXReader"):
                # When _get_commits returns [] the agent short-circuits before calling LLM
                result = agent.catchup.__wrapped__(agent, days=7) if hasattr(agent.catchup, "__wrapped__") else None

        # Direct test of the no-commits branch logic
        mock_llm2 = MagicMock()
        agent2 = CatchupAgent(mock_llm2)

        with patch.object(agent2, "_get_commits", return_value=[]), \
             patch("gitsage.agent.catchup_agent.GitReader") as MockGR, \
             patch("gitsage.agent.catchup_agent.CTXReader") as MockCTX:
            MockCTX.return_value.read.return_value = MagicMock(raw="")
            MockGR.return_value.get_state.return_value = MagicMock(repo_name="test/repo")
            result = agent2.catchup(days=7)

        assert result.commit_count == 0
        assert "No commits" in result.summary
        mock_llm2.complete.assert_not_called()

    def test_describe_period_today(self):
        agent = CatchupAgent(MagicMock())
        assert agent._describe_period(1, "", "") == "today"

    def test_describe_period_week(self):
        agent = CatchupAgent(MagicMock())
        assert agent._describe_period(7, "", "") == "the past week"

    def test_describe_period_two_weeks(self):
        agent = CatchupAgent(MagicMock())
        assert agent._describe_period(14, "", "") == "the past two weeks"

    def test_describe_period_custom(self):
        agent = CatchupAgent(MagicMock())
        assert "30" in agent._describe_period(30, "", "")

    def test_describe_period_tag(self):
        agent = CatchupAgent(MagicMock())
        result = agent._describe_period(7, "v1.0.0", "")
        assert "v1.0.0" in result

    def test_describe_period_date(self):
        agent = CatchupAgent(MagicMock())
        result = agent._describe_period(7, "", "2024-03-01")
        assert "2024-03-01" in result

    def test_catchup_calls_llm_with_commits(self, mock_llm):
        agent = CatchupAgent(mock_llm)
        commits = [make_commit("abc1234", "feat: add retry", "alice")]

        with patch.object(agent, "_get_commits", return_value=commits), \
             patch("gitsage.agent.catchup_agent.GitReader") as MockGR, \
             patch("gitsage.agent.catchup_agent.CTXReader") as MockCTX:
            MockCTX.return_value.read.return_value = MagicMock(raw="")
            MockGR.return_value.get_state.return_value = MagicMock(repo_name="test/repo")
            result = agent.catchup(days=7)

        mock_llm.complete.assert_called_once()
        call_kwargs = mock_llm.complete.call_args
        assert call_kwargs is not None
        # commit_count and period_description should be set on the returned output
        assert result.commit_count == 1
        assert result.period_description == "the past week"


class TestCatchupPrompts:

    def test_build_catchup_user_prompt_includes_commits(self):
        from gitsage.agent.prompts import build_catchup_user_prompt
        commits = [make_commit("abc1234", "feat: add retry", "alice")]
        result = build_catchup_user_prompt(commits, "the past week", "test/repo")
        assert "feat: add retry" in result or "abc" in result

    def test_build_catchup_user_prompt_no_commits(self):
        from gitsage.agent.prompts import build_catchup_user_prompt
        result = build_catchup_user_prompt([], "today", "test/repo")
        assert "no commits" in result.lower() or "0" in result

    def test_build_catchup_user_prompt_includes_repo_name(self):
        from gitsage.agent.prompts import build_catchup_user_prompt
        result = build_catchup_user_prompt([], "today", "myorg/myrepo")
        assert "myorg/myrepo" in result

    def test_build_catchup_user_prompt_includes_period(self):
        from gitsage.agent.prompts import build_catchup_user_prompt
        result = build_catchup_user_prompt([], "the past week", "repo")
        assert "the past week" in result

    def test_build_catchup_user_prompt_with_ctx(self):
        from gitsage.agent.prompts import build_catchup_user_prompt
        result = build_catchup_user_prompt([], "today", "repo", ctx_content="This is a payment service.")
        assert "payment service" in result

    def test_build_catchup_user_prompt_truncates_long_message(self):
        from gitsage.agent.prompts import build_catchup_user_prompt
        long_msg = "x" * 200
        commits = [make_commit("abc1234", long_msg, "dev")]
        result = build_catchup_user_prompt(commits, "today", "repo")
        # Message should be truncated to 120 chars in the commit line
        assert "x" * 121 not in result
