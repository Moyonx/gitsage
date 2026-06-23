"""Tests for user preferences module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from gitsage.preferences import UserPreferences, load_preferences, save_preferences, has_preferences


class TestUserPreferences:

    def test_defaults(self):
        p = UserPreferences()
        assert p.language == "auto"
        assert p.commit_emoji is False
        assert p.commit_scope is True
        assert p.commit_length == "standard"
        assert p.ticket_format == "auto"
        assert p.standup_audience == "technical"
        assert p.standup_format == "bullets"

    def test_to_prompt_hint_zh(self):
        # Language is now handled by language_preamble (placed at prompt top)
        p = UserPreferences(language="zh")
        assert "Chinese" in p.language_preamble or "中文" in p.language_preamble

    def test_language_preamble_zh_is_strong(self):
        p = UserPreferences(language="zh")
        preamble = p.language_preamble
        # Should contain a strong directive and language mention
        has_directive = any(w in preamble for w in ["MUST", "REQUIREMENT", "强制", "必须", "禁止"])
        assert has_directive, "preamble should contain a strong language directive"
        assert "中文" in preamble or "Chinese" in preamble

    def test_to_prompt_hint_en(self):
        # Language is now handled by language_preamble
        p = UserPreferences(language="en")
        assert "English" in p.language_preamble

    def test_language_preamble_auto_is_empty(self):
        p = UserPreferences(language="auto")
        assert p.language_preamble == ""

    def test_to_prompt_hint_auto_no_language_constraint(self):
        p = UserPreferences(language="auto")
        hint = p.to_prompt_hint()
        assert "Output language" not in hint

    def test_to_prompt_hint_emoji_on(self):
        p = UserPreferences(commit_emoji=True)
        hint = p.to_prompt_hint()
        assert "emoji" in hint.lower()
        assert "NOT" not in hint or "Include" in hint

    def test_to_prompt_hint_emoji_off(self):
        p = UserPreferences(commit_emoji=False)
        hint = p.to_prompt_hint()
        assert "NOT" in hint

    def test_to_prompt_hint_brief_length(self):
        p = UserPreferences(commit_length="brief")
        hint = p.to_prompt_hint()
        assert "50" in hint

    def test_to_prompt_hint_detailed_length(self):
        p = UserPreferences(commit_length="detailed")
        hint = p.to_prompt_hint()
        assert "body" in hint.lower() or "WHY" in hint

    def test_to_prompt_hint_jira_ticket(self):
        p = UserPreferences(ticket_format="jira", ticket_pattern="PAY")
        hint = p.to_prompt_hint()
        assert "JIRA" in hint
        assert "PAY" in hint

    def test_to_prompt_hint_no_ticket(self):
        p = UserPreferences(ticket_format="none")
        hint = p.to_prompt_hint()
        assert "ticket" not in hint.lower() and "JIRA" not in hint and "issue" not in hint.lower()

    def test_to_prompt_hint_nontechnical_standup(self):
        p = UserPreferences(standup_audience="nontechnical")
        hint = p.to_prompt_hint()
        assert "NON-TECHNICAL" in hint or "non-technical" in hint.lower()

    def test_to_prompt_hint_is_nonempty(self):
        p = UserPreferences()
        assert len(p.to_prompt_hint()) > 0


class TestSaveLoad:

    def test_save_and_load(self, tmp_path):
        cfg = tmp_path / "config.yml"
        with patch("gitsage.preferences.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.preferences.GLOBAL_CONFIG_DIR", tmp_path):
            p = UserPreferences(language="zh", commit_emoji=True)
            save_preferences(p)
            loaded = load_preferences()

        assert loaded.language == "zh"
        assert loaded.commit_emoji is True

    def test_load_defaults_when_no_file(self, tmp_path):
        with patch("gitsage.preferences.GLOBAL_CONFIG_FILE", tmp_path / "none.yml"):
            loaded = load_preferences()
        assert loaded.language == "auto"

    def test_save_merges_with_existing_config(self, tmp_path):
        cfg = tmp_path / "config.yml"
        cfg.write_text(yaml.dump({"llm": {"provider": "openai"}}))
        with patch("gitsage.preferences.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.preferences.GLOBAL_CONFIG_DIR", tmp_path):
            save_preferences(UserPreferences(language="en"))
        data = yaml.safe_load(cfg.read_text())
        assert data["llm"]["provider"] == "openai"   # preserved
        assert data["preferences"]["language"] == "en"  # added

    def test_has_preferences_false_when_no_file(self, tmp_path):
        with patch("gitsage.preferences.GLOBAL_CONFIG_FILE", tmp_path / "none.yml"):
            assert has_preferences() is False

    def test_has_preferences_true_after_save(self, tmp_path):
        cfg = tmp_path / "config.yml"
        with patch("gitsage.preferences.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.preferences.GLOBAL_CONFIG_DIR", tmp_path):
            save_preferences(UserPreferences())
            assert has_preferences() is True
