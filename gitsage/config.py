"""Configuration management for gitsage."""
from __future__ import annotations

import os
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, model_validator

load_dotenv()

# ---------------------------------------------------------------------------
# Provider constants
# ---------------------------------------------------------------------------

PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}

PROVIDER_ENV_VARS: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# ---------------------------------------------------------------------------
# Environment variable expansion helpers
# ---------------------------------------------------------------------------

_ENV_PATTERN = re.compile(r"\${([^}]+)}")


def _expand_env(value: str) -> str:
    """Expand \${VAR} patterns in *value* using the current environment."""
    def _replace(match: re.Match) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return _ENV_PATTERN.sub(_replace, value)


def _expand_config(obj: Any) -> Any:
    """Recursively expand environment variables in dicts, lists, and strings."""
    if isinstance(obj, dict):
        return {k: _expand_config(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_config(item) for item in obj]
    if isinstance(obj, str):
        return _expand_env(obj)
    return obj


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CommitMode(str, Enum):
    interactive = "interactive"
    print = "print"      # show all candidates with explanations (human-readable)
    execute = "execute"  # silently commit first candidate
    hook = "hook"        # output first candidate message only, no formatting (for git hooks)


# ---------------------------------------------------------------------------
# Pydantic v2 models
# ---------------------------------------------------------------------------

class LLMConfig(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    api_key: str = ""
    base_url: str = ""

    @model_validator(mode="after")
    def _resolve_defaults(self) -> "LLMConfig":
        # Resolve api_key from environment if not set
        if not self.api_key:
            env_var = PROVIDER_ENV_VARS.get(self.provider, "")
            if env_var:
                self.api_key = os.environ.get(env_var, "")

        # Resolve base_url from known providers if not set
        if not self.base_url:
            self.base_url = PROVIDER_BASE_URLS.get(self.provider, "")

        return self

    @property
    def uses_anthropic_sdk(self) -> bool:
        """True when the Anthropic Python SDK should be used for this provider."""
        return self.provider == "anthropic"

    @property
    def uses_openai_sdk(self) -> bool:
        """True when the OpenAI Python SDK should be used for this provider."""
        return self.provider in {"deepseek", "openai", "ollama", "openai-compatible"}


class CommitConfig(BaseModel):
    default_mode: CommitMode = CommitMode.interactive
    max_candidates: int = 3
    max_retries: int = 3


class CTXRules(BaseModel):
    always: list[str] = []
    never: list[str] = []


class GitsageConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    commit: CommitConfig = CommitConfig()
    rules: CTXRules = CTXRules()


# ---------------------------------------------------------------------------
# Config file discovery
# ---------------------------------------------------------------------------

def _find_global_config() -> Optional[Path]:
    """Return ~/.gitsage/config.yml if it exists, otherwise None."""
    candidate = Path.home() / ".gitsage" / "config.yml"
    return candidate if candidate.is_file() else None


def _find_ctx_md(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up directory tree from *start* looking for a CTX.md file."""
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / "CTX.md"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            return None
        current = parent


# ---------------------------------------------------------------------------
# CTX.md rules parsing
# ---------------------------------------------------------------------------

_RULES_SECTION_PATTERN = re.compile(
    r"##\s*(?:规则|rules)[^\n]*\n((?:(?!^##).)+)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)


def _parse_ctx_rules(ctx_content: str) -> CTXRules:
    """Extract and parse a YAML rules block from CTX.md content."""
    match = _RULES_SECTION_PATTERN.search(ctx_content)
    if not match:
        return CTXRules()
    try:
        data = yaml.safe_load(match.group(1)) or {}
        return CTXRules(
            always=data.get("always", []),
            never=data.get("never", []),
        )
    except yaml.YAMLError:
        return CTXRules()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(
    config_file: Optional[Path] = None,
    start: Optional[Path] = None,
) -> GitsageConfig:
    """Load GitsageConfig from *config_file* (or the global default) plus CTX.md rules."""
    # Determine which config file to load
    cfg_path = config_file or _find_global_config()

    raw: dict[str, Any] = {}
    if cfg_path and cfg_path.is_file():
        with cfg_path.open() as fh:
            raw = yaml.safe_load(fh) or {}
        raw = _expand_config(raw)

    config = GitsageConfig(**raw)

    # Overlay CTX.md rules (they take precedence over file-level rules)
    ctx_path = _find_ctx_md(start)
    if ctx_path:
        ctx_rules = _parse_ctx_rules(ctx_path.read_text())
        # Merge: CTX.md rules extend (not replace) file-level rules
        merged_always = list(dict.fromkeys(config.rules.always + ctx_rules.always))
        merged_never = list(dict.fromkeys(config.rules.never + ctx_rules.never))
        config.rules = CTXRules(always=merged_always, never=merged_never)

    return config


@lru_cache(maxsize=1)
def get_config() -> GitsageConfig:
    """Return the singleton GitsageConfig instance."""
    return load_config()
