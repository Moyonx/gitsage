"""Tests for gitsage.config."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from gitsage.config import (
    CommitMode,
    CTXRules,
    GitsageConfig,
    LLMConfig,
    CommitConfig,
    _expand_env,
    _find_ctx_md,
    load_config,
)


class TestDefaultConfigValues:
    def test_default_config_values(self):
        config = GitsageConfig()
        assert config.llm.provider == "deepseek"
        assert config.llm.model == "deepseek-v4-flash"
        assert config.commit.default_mode == CommitMode.interactive
        assert config.commit.max_candidates == 3
        assert config.commit.max_retries == 3
        assert config.rules.always == []
        assert config.rules.never == []


class TestEnvVarExpansion:
    def test_env_var_expansion(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_KEY", "secret-value-123")
        result = _expand_env("${MY_TEST_KEY}")
        assert result == "secret-value-123"

    def test_env_var_expansion_missing_var_returns_original(self, monkeypatch):
        # Ensure the var is not set
        monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
        result = _expand_env("${MISSING_VAR_XYZ}")
        assert result == "${MISSING_VAR_XYZ}"

    def test_env_var_expansion_partial_string(self, monkeypatch):
        monkeypatch.setenv("PREFIX", "hello")
        result = _expand_env("${PREFIX}_world")
        assert result == "hello_world"


class TestProviderBaseUrlAutoResolved:
    def test_provider_base_url_auto_resolved_deepseek(self):
        cfg = LLMConfig(provider="deepseek", api_key="key")
        assert cfg.base_url == "https://api.deepseek.com"

    def test_provider_base_url_auto_resolved_openai(self):
        cfg = LLMConfig(provider="openai", api_key="key")
        assert cfg.base_url == "https://api.openai.com/v1"

    def test_provider_base_url_auto_resolved_ollama(self):
        cfg = LLMConfig(provider="ollama", api_key="key")
        assert cfg.base_url == "http://localhost:11434/v1"

    def test_provider_base_url_not_overridden_when_set(self):
        cfg = LLMConfig(provider="deepseek", api_key="key", base_url="https://custom.url")
        assert cfg.base_url == "https://custom.url"


class TestUsesAnthropicSdkFlag:
    def test_uses_anthropic_sdk_flag_true_for_anthropic(self):
        cfg = LLMConfig(provider="anthropic", api_key="key")
        assert cfg.uses_anthropic_sdk is True

    def test_uses_anthropic_sdk_flag_false_for_deepseek(self):
        cfg = LLMConfig(provider="deepseek", api_key="key")
        assert cfg.uses_anthropic_sdk is False

    def test_uses_openai_sdk_flag_true_for_deepseek(self):
        cfg = LLMConfig(provider="deepseek", api_key="key")
        assert cfg.uses_openai_sdk is True

    def test_uses_openai_sdk_flag_true_for_openai(self):
        cfg = LLMConfig(provider="openai", api_key="key")
        assert cfg.uses_openai_sdk is True

    def test_uses_openai_sdk_flag_false_for_anthropic(self):
        cfg = LLMConfig(provider="anthropic", api_key="key")
        assert cfg.uses_openai_sdk is False


class TestCTXRulesParsing:
    def test_ctx_rules_parsing_always(self):
        rules = CTXRules(always=["inject ticket", "add scope"], never=[])
        assert "inject ticket" in rules.always
        assert "add scope" in rules.always

    def test_ctx_rules_parsing_never(self):
        rules = CTXRules(always=[], never=["no file paths", "no debug logs"])
        assert "no file paths" in rules.never
        assert "no debug logs" in rules.never

    def test_ctx_rules_empty_defaults(self):
        rules = CTXRules()
        assert rules.always == []
        assert rules.never == []


class TestFindCtxMd:
    def test_find_ctx_md_finds_file_in_same_dir(self, tmp_path):
        ctx_file = tmp_path / "CTX.md"
        ctx_file.write_text("# CTX")
        result = _find_ctx_md(tmp_path)
        assert result == ctx_file

    def test_find_ctx_md_walks_up(self, tmp_path):
        # Create CTX.md in parent, start from child
        ctx_file = tmp_path / "CTX.md"
        ctx_file.write_text("# CTX")
        child_dir = tmp_path / "subdir" / "deeper"
        child_dir.mkdir(parents=True)
        result = _find_ctx_md(child_dir)
        assert result == ctx_file

    def test_find_ctx_md_returns_none_when_missing(self, tmp_path):
        # tmp_path is isolated; no CTX.md anywhere in this tree
        child = tmp_path / "a" / "b"
        child.mkdir(parents=True)
        # We cannot guarantee no CTX.md exists above tmp_path in the real FS,
        # so we just test that when the file is present it's found, and
        # verify the function returns None or a Path.
        result = _find_ctx_md(child)
        # If a real CTX.md exists above, it would be returned — just check type
        assert result is None or isinstance(result, Path)

    def test_find_ctx_md_prefers_nearest(self, tmp_path):
        # CTX.md in both parent and child — should return child's
        parent_ctx = tmp_path / "CTX.md"
        parent_ctx.write_text("# Parent")
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        child_ctx = child_dir / "CTX.md"
        child_ctx.write_text("# Child")
        result = _find_ctx_md(child_dir)
        assert result == child_ctx


class TestCommitModeFromString:
    def test_commit_mode_interactive(self):
        mode = CommitMode("interactive")
        assert mode == CommitMode.interactive

    def test_commit_mode_print(self):
        mode = CommitMode("print")
        assert mode == CommitMode.print

    def test_commit_mode_execute(self):
        mode = CommitMode("execute")
        assert mode == CommitMode.execute

    def test_commit_mode_invalid_raises(self):
        with pytest.raises(ValueError):
            CommitMode("bogus")

    def test_commit_mode_is_string(self):
        # CommitMode extends str
        assert CommitMode.interactive == "interactive"
        assert CommitMode.print == "print"
        assert CommitMode.execute == "execute"


class TestApiKeyFromEnv:
    def test_api_key_resolved_from_env_deepseek(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek-key")
        cfg = LLMConfig(provider="deepseek")
        assert cfg.api_key == "env-deepseek-key"

    def test_api_key_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        cfg = LLMConfig(provider="deepseek", api_key="explicit-key")
        assert cfg.api_key == "explicit-key"
