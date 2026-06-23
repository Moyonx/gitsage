"""Tests for gitsage harness modules: quality_gate, override, hooks."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from gitsage.config import CTXRules
from gitsage.harness.quality_gate import QualityGate, Rule, GateResult
from gitsage.harness.override import DeterministicOverride
from gitsage.harness.hooks import HookRunner, HookEvent, HookResult


# ---------------------------------------------------------------------------
# QualityGate tests
# ---------------------------------------------------------------------------

class TestQualityGatePassesValidCommit:
    def test_quality_gate_passes_valid_commit(self):
        gate = QualityGate.for_commit(max_chars=72)
        result = gate.check("feat(auth): add OAuth2 login support")
        assert result.passed is True
        assert result.violations == []

    def test_quality_gate_passes_short_message(self):
        gate = QualityGate.for_commit(max_chars=72)
        result = gate.check("fix: typo in README")
        assert result.passed is True


class TestQualityGateFailsTooLong:
    def test_quality_gate_fails_too_long(self):
        gate = QualityGate.for_commit(max_chars=72)
        # 80-char message exceeds the 72-char limit
        long_msg = "feat(auth): " + "a" * 68  # total > 72
        result = gate.check(long_msg)
        assert result.passed is False
        assert any("Too long" in v.message or "length" in v.message.lower() for v in result.violations)

    def test_quality_gate_fails_exactly_at_limit(self):
        gate = QualityGate.for_commit(max_chars=10)
        result = gate.check("12345678901")  # 11 chars > 10
        assert result.passed is False

    def test_quality_gate_passes_at_limit(self):
        gate = QualityGate.for_commit(max_chars=10)
        result = gate.check("1234567890")  # exactly 10
        assert result.passed is True


class TestQualityGateForCommitFactory:
    def test_quality_gate_for_commit_factory(self):
        gate = QualityGate.for_commit(max_chars=72, language="en")
        assert isinstance(gate, QualityGate)
        # Should have rules
        assert len(gate._rules) > 0

    def test_quality_gate_for_commit_custom_max_chars(self):
        gate = QualityGate.for_commit(max_chars=50)
        # 51-char message should fail
        result = gate.check("a" * 51)
        assert result.passed is False

    def test_quality_gate_for_standup(self):
        gate = QualityGate.for_standup()
        assert isinstance(gate, QualityGate)

    def test_quality_gate_standup_fails_short(self):
        gate = QualityGate.for_standup()
        result = gate.check("hi")
        assert result.passed is False

    def test_quality_gate_standup_passes_long_enough(self):
        gate = QualityGate.for_standup()
        result = gate.check("Yesterday I worked on the payment module and fixed the retry bug.")
        assert result.passed is True

    def test_quality_gate_fails_empty(self):
        gate = QualityGate.for_commit(max_chars=72)
        result = gate.check("")
        assert result.passed is False

    def test_gate_result_message_ok_when_passed(self):
        gate = QualityGate.for_commit(max_chars=72)
        result = gate.check("fix: small change")
        assert result.message == "OK"

    def test_gate_result_message_describes_violation(self):
        gate = QualityGate.for_commit(max_chars=5)
        result = gate.check("this is way too long")
        assert result.passed is False
        assert result.message != "OK"


# ---------------------------------------------------------------------------
# DeterministicOverride tests
# ---------------------------------------------------------------------------

class TestDeterministicOverrideInjectsTicket:
    def test_deterministic_override_injects_ticket(self):
        rules = CTXRules(always=["inject ticket"], never=[])
        override = DeterministicOverride(rules=rules, branch_name="feature/PAY-234-payment-retry")
        result = override.apply_to_commit("feat(payment): add retry mechanism")
        assert "[PAY-234]" in result

    def test_deterministic_override_injects_ticket_uppercase(self):
        rules = CTXRules(always=["inject ticket"], never=[])
        override = DeterministicOverride(rules=rules, branch_name="feature/jira-567-fix-bug")
        result = override.apply_to_commit("fix: resolve the bug")
        assert "[JIRA-567]" in result


class TestDeterministicOverrideNoTicketWhenBranchClean:
    def test_deterministic_override_no_ticket_when_branch_clean(self):
        rules = CTXRules(always=["inject ticket"], never=[])
        override = DeterministicOverride(rules=rules, branch_name="main")
        result = override.apply_to_commit("feat: add new feature")
        # No ticket pattern in branch name — no injection
        assert "[" not in result or "]" not in result

    def test_deterministic_override_no_ticket_plain_branch(self):
        rules = CTXRules(always=["inject ticket"], never=[])
        override = DeterministicOverride(rules=rules, branch_name="feature/no-ticket-here")
        result = override.apply_to_commit("fix: something")
        # No JIRA-style ticket pattern
        import re
        assert not re.search(r'\[[A-Z]+-\d+\]', result)


class TestDeterministicOverrideSkipsIfTicketAlreadyPresent:
    def test_deterministic_override_skips_if_ticket_already_present(self):
        rules = CTXRules(always=["inject ticket"], never=[])
        override = DeterministicOverride(rules=rules, branch_name="feature/PAY-234-retry")
        # Message already contains the ticket
        result = override.apply_to_commit("feat(payment): add retry [PAY-234]")
        # Should not double-inject
        assert result.count("[PAY-234]") == 1

    def test_deterministic_override_skips_case_insensitive(self):
        rules = CTXRules(always=["inject ticket"], never=[])
        override = DeterministicOverride(rules=rules, branch_name="feature/PAY-234-retry")
        result = override.apply_to_commit("feat: add retry [pay-234]")
        # Ticket already present (case-insensitive match)
        assert result.count("PAY-234") <= 1


class TestDeterministicOverrideFilterForbidden:
    def test_filter_forbidden_removes_file_paths(self):
        rules = CTXRules(always=[], never=["no file paths"])
        override = DeterministicOverride(rules=rules, branch_name="main")
        result = override.apply_to_commit("fix: updated src/payment/retry.py logic")
        # File path should be removed
        assert "src/payment/retry.py" not in result

    def test_check_never_rules_returns_violations(self):
        rules = CTXRules(always=[], never=["no debug statements"])
        override = DeterministicOverride(rules=rules, branch_name="main")
        violations = override.check_never_rules("add debug logging")
        assert len(violations) > 0

    def test_check_never_rules_empty_when_clean(self):
        rules = CTXRules(always=[], never=["no debug statements"])
        override = DeterministicOverride(rules=rules, branch_name="main")
        violations = override.check_never_rules("feat: add payment retry")
        assert violations == []


# ---------------------------------------------------------------------------
# HookRunner tests
# ---------------------------------------------------------------------------

class TestHookRunnerNoHookReturnsNotRan:
    def test_hook_runner_no_hook_returns_not_ran(self, tmp_path):
        runner = HookRunner(repo_path=tmp_path)
        result = runner.run(HookEvent.PRE_COMMIT)
        assert result.ran is False
        assert result.success is True

    def test_hook_runner_no_hook_post_standup(self, tmp_path):
        runner = HookRunner(repo_path=tmp_path)
        result = runner.run(HookEvent.POST_STANDUP)
        assert result.ran is False


class TestHookRunnerRunsScript:
    def test_hook_runner_runs_script(self, tmp_path):
        hooks_dir = tmp_path / ".gitsage" / "hooks"
        hooks_dir.mkdir(parents=True)
        script = hooks_dir / "pre-commit.sh"
        script.write_text("#!/bin/bash\necho 'hook ran'\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        runner = HookRunner(repo_path=tmp_path)
        result = runner.run(HookEvent.PRE_COMMIT)

        assert result.ran is True
        assert result.success is True
        assert "hook ran" in result.output

    def test_hook_runner_captures_failure(self, tmp_path):
        hooks_dir = tmp_path / ".gitsage" / "hooks"
        hooks_dir.mkdir(parents=True)
        script = hooks_dir / "pre-commit.sh"
        script.write_text("#!/bin/bash\nexit 1\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        runner = HookRunner(repo_path=tmp_path)
        result = runner.run(HookEvent.PRE_COMMIT)

        assert result.ran is True
        assert result.success is False

    def test_hook_runner_passes_env(self, tmp_path):
        hooks_dir = tmp_path / ".gitsage" / "hooks"
        hooks_dir.mkdir(parents=True)
        script = hooks_dir / "pre-commit.sh"
        script.write_text("#!/bin/bash\necho \"VALUE=$MY_TEST_VAR\"\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        runner = HookRunner(repo_path=tmp_path)
        result = runner.run(HookEvent.PRE_COMMIT, env={"MY_TEST_VAR": "hello123"})

        assert result.ran is True
        assert "hello123" in result.output
