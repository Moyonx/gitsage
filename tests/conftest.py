"""Shared test fixtures for gitsage."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gitsage.config import CommitConfig, CommitMode, CTXRules, GitsageConfig, LLMConfig
from gitsage.agent.models import CommitCandidate, CommitOutput, StandupOutput
from gitsage.context.git_reader import CommitInfo, GitState
from gitsage.context.ctx_reader import CTXContent


@pytest.fixture
def sample_config():
    return GitsageConfig(
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", api_key="test-key"),
        commit=CommitConfig(default_mode=CommitMode.interactive),
        rules=CTXRules(always=["inject ticket"], never=["no file paths"]),
    )


@pytest.fixture
def sample_commit_output():
    return CommitOutput(
        candidates=[
            CommitCandidate(
                message="feat(payment): add retry mechanism [PAY-234]",
                confidence="high",
                reason="Clear intent from diff",
            ),
            CommitCandidate(
                message="feat: add payment retry logic",
                confidence="medium",
                reason="Missing scope",
            ),
        ],
        warning=None,
    )


@pytest.fixture
def sample_git_state():
    return GitState(
        repo_path=Path("/tmp/test-repo"),
        repo_name="owner/test-repo",
        branch_name="feature/PAY-234-payment-retry",
        staged_diff=(
            "+def retry_payment(order_id):\n"
            "+    for i in range(3):\n"
            "+        result = charge(order_id)\n"
            "+        if result.success:\n"
            "+            return result"
        ),
        staged_files=["src/payment/retry.py"],
        staged_summary="1 file changed, +5/-0",
        recent_commits=[],
        today_commits=[],
        is_clean=False,
    )


@pytest.fixture
def sample_ctx_content():
    return CTXContent(
        raw=(
            "# CTX.md\n"
            "## Commit 规范\n"
            "格式：feat(<模块>): <描述>\n"
            "## Rules\n"
            "always:\n"
            "  - inject ticket\n"
            "never:\n"
            "  - no file paths"
        ),
        project_background="Test project",
        commit_rules="格式：feat(<模块>): <描述>",
        standup_format="",
        pr_rules="",
        always_rules=["inject ticket"],
        never_rules=["no file paths"],
        language="zh",
        is_empty=False,
    )
