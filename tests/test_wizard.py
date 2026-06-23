"""Tests for the LLM setup wizard."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ── is_llm_configured ─────────────────────────────────────────────────────────

class TestIsLlmConfigured:

    def test_returns_false_when_nothing(self, tmp_path, monkeypatch):
        for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.setenv(v, "")
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", tmp_path / "config.yml"), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import is_llm_configured
            assert is_llm_configured() is False

    def test_returns_true_when_openai_env_set(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from gitsage.wizard import is_llm_configured
        assert is_llm_configured() is True

    def test_returns_true_when_deepseek_env_set(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deep-test")
        from gitsage.wizard import is_llm_configured
        assert is_llm_configured() is True

    def test_returns_true_when_anthropic_env_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        from gitsage.wizard import is_llm_configured
        assert is_llm_configured() is True

    def test_returns_true_when_global_config_has_openai(self, tmp_path, monkeypatch):
        for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.setenv(v, "")
        cfg = tmp_path / "config.yml"
        cfg.write_text(yaml.dump({
            "llm": {"provider": "openai", "api_key": "sk-x", "model": "gpt-4o", "base_url": ""}
        }))
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import is_llm_configured
            assert is_llm_configured() is True

    def test_returns_true_for_ollama_with_model(self, tmp_path, monkeypatch):
        for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.setenv(v, "")
        cfg = tmp_path / "config.yml"
        cfg.write_text(yaml.dump({"llm": {"provider": "ollama", "model": "qwen2.5:14b"}}))
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import is_llm_configured
            assert is_llm_configured() is True

    def test_returns_false_for_ollama_without_model(self, tmp_path, monkeypatch):
        for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.setenv(v, "")
        cfg = tmp_path / "config.yml"
        cfg.write_text(yaml.dump({"llm": {"provider": "ollama", "model": ""}}))
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import is_llm_configured
            assert is_llm_configured() is False


# ── detect_config ─────────────────────────────────────────────────────────────

class TestDetectConfig:

    def _clear_env(self, monkeypatch):
        for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.setenv(v, "")

    def test_returns_none_when_nothing(self, tmp_path, monkeypatch):
        self._clear_env(monkeypatch)
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", tmp_path / "no.yml"), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import detect_config
            assert detect_config() is None

    def test_detects_openai_env_var(self, tmp_path, monkeypatch):
        self._clear_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-xyz")
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", tmp_path / "no.yml"), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import detect_config
            result = detect_config()
            assert result is not None
            assert result.provider == "openai"
            assert result.api_key == "sk-openai-xyz"
            assert "OPENAI_API_KEY" in result.source

    def test_detects_deepseek_env_var_as_openai_compatible(self, tmp_path, monkeypatch):
        self._clear_env(monkeypatch)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deep-xyz")
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", tmp_path / "no.yml"), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import detect_config
            result = detect_config()
            assert result is not None
            assert result.provider == "openai-compatible"
            assert result.base_url == "https://api.deepseek.com"

    def test_global_config_takes_priority_over_env(self, tmp_path, monkeypatch):
        self._clear_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
        cfg = tmp_path / "config.yml"
        cfg.write_text(yaml.dump({
            "llm": {
                "provider": "openai-compatible",
                "api_key": "sk-file-key",
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com",
            }
        }))
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path):
            from gitsage.wizard import detect_config
            result = detect_config()
            assert result is not None
            assert result.api_key == "sk-file-key"   # file wins over env
            assert "全局配置" in result.source

    def test_local_project_config_takes_highest_priority(self, tmp_path, monkeypatch):
        self._clear_env(monkeypatch)
        # Global config
        global_cfg = tmp_path / "global.yml"
        global_cfg.write_text(yaml.dump({
            "llm": {"provider": "openai", "api_key": "sk-global", "model": "gpt-4o", "base_url": ""}
        }))
        # Local project config
        local_dir = tmp_path / "project" / ".gitsage"
        local_dir.mkdir(parents=True)
        local_cfg = local_dir / "config.yml"
        local_cfg.write_text(yaml.dump({
            "llm": {
                "provider": "openai-compatible",
                "api_key": "sk-local",
                "model": "local-model",
                "base_url": "http://localhost:8080/v1",
            }
        }))
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", global_cfg), \
             patch("gitsage.wizard.Path.cwd", return_value=tmp_path / "project"):
            from gitsage.wizard import detect_config
            result = detect_config()
            assert result is not None
            assert result.api_key == "sk-local"   # local wins
            assert "项目配置" in result.source


# ── _save_global_config ───────────────────────────────────────────────────────

class TestSaveGlobalConfig:

    def test_saves_llm_block(self, tmp_path):
        cfg = tmp_path / "config.yml"
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.wizard.GLOBAL_CONFIG_DIR", tmp_path):
            from gitsage.wizard import _save_global_config
            _save_global_config({"llm": {"provider": "openai", "model": "gpt-4o"}})
        data = yaml.safe_load(cfg.read_text())
        assert data["llm"]["provider"] == "openai"

    def test_merges_without_overwriting_other_keys(self, tmp_path):
        cfg = tmp_path / "config.yml"
        cfg.write_text(yaml.dump({"privacy_consent": True}))
        with patch("gitsage.wizard.GLOBAL_CONFIG_FILE", cfg), \
             patch("gitsage.wizard.GLOBAL_CONFIG_DIR", tmp_path):
            from gitsage.wizard import _save_global_config
            _save_global_config({"llm": {"provider": "ollama", "model": "qwen2.5:14b"}})
        data = yaml.safe_load(cfg.read_text())
        assert data["privacy_consent"] is True      # preserved
        assert data["llm"]["provider"] == "ollama"  # added


# ── Provider catalogue ────────────────────────────────────────────────────────

class TestProviderCatalogue:

    def test_has_exactly_three_providers(self):
        from gitsage.wizard import PROVIDERS
        assert len(PROVIDERS) == 3

    def test_provider_1_is_ollama(self):
        from gitsage.wizard import PROVIDERS
        p = PROVIDERS["1"]
        assert p["id"] == "ollama"
        assert p["api_key_required"] is False
        assert p["env_var"] is None

    def test_provider_2_is_openai(self):
        from gitsage.wizard import PROVIDERS
        p = PROVIDERS["2"]
        assert p["id"] == "openai"
        assert p["api_key_required"] is True
        assert p["default_base_url"] == "https://api.openai.com/v1"
        assert p["env_var"] == "OPENAI_API_KEY"

    def test_provider_3_is_custom_openai_compatible(self):
        from gitsage.wizard import PROVIDERS
        p = PROVIDERS["3"]
        assert p["id"] == "openai-compatible"
        assert p["api_key_required"] is True
        assert p["default_base_url"] == ""   # user must provide
        assert p["default_model"] == ""      # user must provide

    def test_deepseek_not_a_named_provider(self):
        from gitsage.wizard import PROVIDERS
        ids = {p["id"] for p in PROVIDERS.values()}
        assert "deepseek" not in ids

    def test_all_providers_have_required_keys(self):
        from gitsage.wizard import PROVIDERS
        required = {"id", "label", "api_key_required", "default_base_url", "default_model"}
        for key, p in PROVIDERS.items():
            missing = required - set(p.keys())
            assert not missing, f"Provider [{key}] missing: {missing}"


# ── _mask_key ─────────────────────────────────────────────────────────────────

class TestMaskKey:

    def test_masks_long_key(self):
        from gitsage.wizard import _mask_key
        result = _mask_key("sk-abcdefghijklmno")
        assert "****" in result
        assert result.endswith("lmno")
        assert "sk-abcdefghijk" not in result

    def test_masks_short_key(self):
        from gitsage.wizard import _mask_key
        assert _mask_key("short") == "****"

    def test_empty_returns_placeholder(self):
        from gitsage.wizard import _mask_key
        assert "（无）" in _mask_key("")
