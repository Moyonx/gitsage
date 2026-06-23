"""Interactive LLM setup wizard for gitsage.

Detection order:
  1. Environment variables (OPENAI_API_KEY etc.)
  2. ~/.gitsage/config.yml  (global config)
  3. .gitsage/config.yml in current working directory (project config)

If any config is found the user is shown what was detected and can:
  - Accept it as-is
  - Adjust individual parameters
  - Discard and start a fresh setup

If nothing is found a simplified three-option menu is shown:
  [1] Local model via Ollama   (free, private)
  [2] OpenAI API
  [3] Custom endpoint          (OpenAI-compatible: DeepSeek, company LLM …)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import print as rprint

console = Console()

GLOBAL_CONFIG_DIR = Path.home() / ".gitsage"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yml"


# ── Provider catalogue (simplified: Ollama / OpenAI / Custom) ───────────────

PROVIDERS = {
    "1": {
        "id": "ollama",
        "label": "本地模型 Ollama（免费，数据完全不出网）",
        "note": "需要先安装 Ollama → https://ollama.com",
        "api_key_required": False,
        "default_base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5:14b",
        "env_var": None,
    },
    "2": {
        "id": "openai",
        "label": "OpenAI API",
        "note": "https://platform.openai.com",
        "api_key_required": True,
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "env_var": "OPENAI_API_KEY",
    },
    "3": {
        "id": "openai-compatible",
        "label": "自定义端点（兼容 OpenAI 格式）",
        "note": "支持 DeepSeek、公司内网 LLM、LM Studio 等任意 OpenAI-compatible 接口",
        "api_key_required": True,
        "default_base_url": "",
        "default_model": "",
        "env_var": None,
    },
}


# ── Detected config dataclass ─────────────────────────────────────────────────

@dataclass
class DetectedConfig:
    """Holds an LLM configuration that was auto-detected from the environment."""
    provider: str
    api_key: str
    base_url: str
    model: str
    source: str   # human-readable description of where it came from

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
        }


# ── Config I/O helpers ────────────────────────────────────────────────────────

def _load_config_file(path: Path) -> dict:
    if path.exists():
        try:
            return yaml.safe_load(path.read_text()) or {}
        except Exception:
            return {}
    return {}


def _load_global_config() -> dict:
    return _load_config_file(GLOBAL_CONFIG_FILE)


def _load_local_config() -> dict:
    """Try to load a project-level .gitsage/config.yml from cwd."""
    local = Path.cwd() / ".gitsage" / "config.yml"
    return _load_config_file(local)


def _save_global_config(data: dict) -> None:
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_global_config()
    existing.update(data)
    GLOBAL_CONFIG_FILE.write_text(yaml.dump(existing, allow_unicode=True))


# ── Detection logic ────────────────────────────────────────────────────────────

_ENV_PROVIDERS = {
    "OPENAI_API_KEY": ("openai", "https://api.openai.com/v1", "gpt-4o"),
    "ANTHROPIC_API_KEY": ("anthropic", "", "claude-sonnet-4-6"),
    "DEEPSEEK_API_KEY": ("openai-compatible", "https://api.deepseek.com", "deepseek-v4-flash"),
}


def detect_config() -> Optional[DetectedConfig]:
    """Scan environment variables and config files for an existing LLM config.

    Priority: local project config > global config file > environment variables.
    Returns the first usable config found, or None.
    """
    # 1. Local project config (.gitsage/config.yml in cwd)
    local = _load_local_config()
    if local.get("llm"):
        llm = local["llm"]
        if _is_valid_llm_block(llm):
            return DetectedConfig(
                provider=llm.get("provider", ""),
                api_key=llm.get("api_key", ""),
                base_url=llm.get("base_url", ""),
                model=llm.get("model", ""),
                source=f"项目配置 ({Path.cwd() / '.gitsage' / 'config.yml'})",
            )

    # 2. Global config file (~/.gitsage/config.yml)
    global_data = _load_global_config()
    if global_data.get("llm"):
        llm = global_data["llm"]
        if _is_valid_llm_block(llm):
            return DetectedConfig(
                provider=llm.get("provider", ""),
                api_key=llm.get("api_key", ""),
                base_url=llm.get("base_url", ""),
                model=llm.get("model", ""),
                source=f"全局配置 ({GLOBAL_CONFIG_FILE})",
            )

    # 3. Environment variables
    for env_var, (provider, base_url, model) in _ENV_PROVIDERS.items():
        val = os.environ.get(env_var, "")
        if val:
            return DetectedConfig(
                provider=provider,
                api_key=val,
                base_url=base_url,
                model=model,
                source=f"环境变量 {env_var}",
            )

    return None


def _is_valid_llm_block(llm: dict) -> bool:
    """Return True if the llm config block has enough to be usable."""
    provider = llm.get("provider", "")
    if not provider:
        return False
    if provider == "ollama":
        return bool(llm.get("model"))
    # Cloud/custom: need api_key and model at minimum
    return bool(llm.get("api_key") and llm.get("model"))


def is_llm_configured() -> bool:
    """Return True if any usable LLM configuration exists."""
    return detect_config() is not None


# ── Display helpers ────────────────────────────────────────────────────────────

def _mask_key(key: str) -> str:
    if not key:
        return "[dim]（无）[/dim]"
    if len(key) <= 8:
        return "****"
    return f"{'*' * 8}...{key[-4:]}"


def _show_config_table(cfg: DetectedConfig, title: str = "检测到的配置") -> None:
    table = Table(title=f"[bold]{title}[/bold]", show_header=True, header_style="bold cyan")
    table.add_column("参数", style="dim")
    table.add_column("值")

    table.add_row("来源", f"[dim]{cfg.source}[/dim]")
    table.add_row("provider", cfg.provider)
    table.add_row("api_key", _mask_key(cfg.api_key))
    table.add_row("base_url", cfg.base_url or "[dim]（自动）[/dim]")
    table.add_row("model", cfg.model)

    console.print()
    console.print(table)


# ── Adjust existing config ─────────────────────────────────────────────────────

def _adjust_config(cfg: DetectedConfig) -> Optional[dict]:
    """Let the user adjust each parameter of a detected config.

    Shows current value as default; user presses Enter to keep it.
    Returns updated dict or None if cancelled.
    """
    console.print()
    console.print("[bold]调整配置参数：[/bold]")
    console.print("[dim]按 Enter 保留当前值，直接输入新值覆盖[/dim]\n")

    params: dict = {"provider": cfg.provider}

    # provider (allow change)
    provider = Prompt.ask("  provider", default=cfg.provider)
    params["provider"] = provider.strip()

    # api_key
    if cfg.api_key:
        console.print(f"  [dim]当前 api_key: {_mask_key(cfg.api_key)}[/dim]")
        change_key = Confirm.ask("  更换 api_key？", default=False)
        if change_key:
            new_key = Prompt.ask("  新 api_key", password=True)
            params["api_key"] = new_key.strip()
        else:
            params["api_key"] = cfg.api_key
    else:
        api_key = Prompt.ask("  api_key（可选）", default="")
        params["api_key"] = api_key.strip()

    # base_url
    base_url = Prompt.ask("  base_url", default=cfg.base_url or "")
    params["base_url"] = base_url.strip()

    # model
    model = Prompt.ask("  model", default=cfg.model)
    if not model.strip():
        rprint("[red]model 不能为空[/red]")
        return None
    params["model"] = model.strip()

    return params


# ── Fresh setup (simplified 3-option menu) ─────────────────────────────────────

def _run_fresh_setup() -> Optional[dict]:
    """Show the simplified provider menu and collect params."""
    console.print()
    console.print("[bold]选择 LLM 提供方：[/bold]\n")

    for key, p in PROVIDERS.items():
        console.print(f"  [bold cyan][{key}][/bold cyan] {p['label']}")
        if p["note"]:
            console.print(f"       [dim]{p['note']}[/dim]")
        console.print()

    choice = Prompt.ask("请选择", choices=list(PROVIDERS.keys()) + ["q"], default="1")
    if choice == "q":
        return None

    provider = PROVIDERS[choice]

    # Ollama: check install first
    if provider["id"] == "ollama":
        console.print()
        rprint("[cyan]Ollama 安装说明：[/cyan]")
        rprint("  macOS :  brew install ollama")
        rprint("  Linux :  curl -fsSL https://ollama.com/install.sh | sh")
        rprint("  下载模型: ollama pull qwen2.5:14b")
        console.print()
        if not Confirm.ask("已安装 Ollama 并下载好模型？", default=False):
            rprint("\n[dim]安装好后重新运行 gitsage setup[/dim]")
            return None

    return _collect_params(provider)


def _collect_params(provider: dict) -> Optional[dict]:
    """Collect and confirm the three parameters for a provider."""
    pid = provider["id"]

    console.print()
    console.print(f"[bold]填写 {pid} 参数：[/bold]")
    console.print("[dim]按 Enter 接受括号内的默认值[/dim]\n")

    params: dict = {"provider": pid}

    # api_key ─────────────────────────────────────────────────────────────────
    if provider["api_key_required"]:
        env_var = provider.get("env_var")
        env_val = os.environ.get(env_var, "") if env_var else ""
        if env_val:
            rprint(f"  [green]✅ 已从环境变量 {env_var} 读取 api_key[/green]")
            params["api_key"] = env_val
        else:
            api_key = Prompt.ask("  api_key", password=True)
            if not api_key.strip():
                rprint("[red]api_key 不能为空[/red]")
                return None
            params["api_key"] = api_key.strip()
    else:
        params["api_key"] = ""

    # base_url ─────────────────────────────────────────────────────────────────
    default_url = provider["default_base_url"]
    if pid == "ollama":
        console.print(f"  [dim]base_url 默认: {default_url}[/dim]")
        params["base_url"] = default_url
    else:
        base_url = Prompt.ask("  base_url", default=default_url)
        params["base_url"] = base_url.strip()

    # model ───────────────────────────────────────────────────────────────────
    default_model = provider["default_model"]
    model = Prompt.ask("  model", default=default_model)
    if not model.strip():
        rprint("[red]model 不能为空[/red]")
        return None
    params["model"] = model.strip()

    return params


# ── Confirmation table ─────────────────────────────────────────────────────────

def _show_confirmation(params: dict) -> bool:
    """Show a summary table and ask for final confirmation."""
    console.print()
    table = Table(title="[bold]配置确认[/bold]", show_header=True, header_style="bold cyan")
    table.add_column("参数", style="dim")
    table.add_column("值")

    table.add_row("provider", params.get("provider", ""))
    table.add_row("api_key", _mask_key(params.get("api_key", "")))
    table.add_row("base_url", params.get("base_url") or "[dim]（自动）[/dim]")
    table.add_row("model", params.get("model", ""))

    console.print(table)
    console.print()
    return Confirm.ask("确认保存？", default=True)


# ── Connection test ────────────────────────────────────────────────────────────

def _test_connection(params: dict) -> bool:
    console.print("\n[dim]正在测试连接...[/dim]")
    try:
        from .config import LLMConfig
        from .agent.llm import create_llm_client
        from .agent.models import StandupOutput

        cfg = LLMConfig(
            provider=params["provider"],
            model=params["model"],
            api_key=params.get("api_key", ""),
            base_url=params.get("base_url", ""),
        )
        create_llm_client(cfg).complete(
            system='Reply with JSON: {"content":"ok","items":[]}',
            user="ping",
            output_model=StandupOutput,
        )
        rprint("[green]✅ 连接成功！[/green]")
        return True
    except Exception as e:
        rprint(f"[yellow]⚠️  连接测试失败: {e}[/yellow]")
        rprint("[dim]配置已保存，可稍后用 gitsage model test 重新测试[/dim]")
        return False


# ── Main entry point ───────────────────────────────────────────────────────────

def run_setup_wizard(skip_banner: bool = False) -> bool:
    """Run the setup wizard with smart detection.

    Flow:
      1. Detect any existing config (local file → global file → env var)
      2. If found: show it and ask to use / adjust / setup-fresh
      3. If not found: show simplified 3-option provider menu
      4. Confirm the three parameters, save, optionally test

    Returns True if a configuration was saved, False if cancelled.
    """
    detected = detect_config()

    # ── Branch A: existing config detected ────────────────────────────────────
    if detected:
        _show_config_table(detected, title="检测到已有 LLM 配置")
        console.print()

        choice = Prompt.ask(
            "如何处理？",
            choices=["u", "a", "n", "q"],
            default="u",
            show_choices=False,
        )
        # Print choices manually for nicer formatting
        # (shown before the prompt above via console.print)
        console.print(
            "  [dim][u] 直接使用  [a] 调整参数  [n] 重新设置  [q] 退出[/dim]",
            highlight=False,
        )
        # Re-prompt with visible hint (second call for real input)
        choice = Prompt.ask(
            "请输入",
            choices=["u", "a", "n", "q"],
            default="u",
        )

        if choice == "q":
            rprint("\n[dim]已退出。运行 gitsage setup 可重新配置。[/dim]")
            return False

        if choice == "u":
            # Use as-is — nothing to save (already configured)
            rprint("\n[green]✅ 使用已检测到的配置[/green]")
            return True

        if choice == "a":
            # Adjust existing
            params = _adjust_config(detected)
            if params is None:
                return False
        else:
            # choice == "n" — fresh setup
            params = _run_fresh_setup()
            if params is None:
                return False

    # ── Branch B: nothing detected ────────────────────────────────────────────
    else:
        if not skip_banner:
            console.print()
            console.print(Panel(
                "[bold]未检测到 LLM 配置[/bold]\n\n"
                "gitsage 需要一个 AI 模型来理解你的代码变更，配置只需一次。",
                title="[bold cyan]🤔 首次使用 gitsage[/bold cyan]",
                expand=False,
            ))

        params = _run_fresh_setup()
        if params is None:
            rprint("\n[dim]已取消。运行 gitsage setup 可随时配置。[/dim]")
            return False

    # ── Confirm and save ──────────────────────────────────────────────────────
    if not _show_confirmation(params):
        if Confirm.ask("重新配置？", default=True):
            return run_setup_wizard(skip_banner=True)
        return False

    _save_global_config({"llm": params})
    rprint(f"\n[green]✅ 配置已保存到 {GLOBAL_CONFIG_FILE}[/green]")

    # Test connection (optional)
    console.print()
    if Confirm.ask("现在测试连接？", default=True):
        _test_connection(params)

    # Preferences survey — only prompt if not already set
    from .preferences import has_preferences, run_preferences_survey
    console.print()
    if not has_preferences():
        if Confirm.ask("设置个人偏好（语言、commit 风格等）？只需 1 分钟", default=True):
            run_preferences_survey(skip_banner=True)
    else:
        rprint("[dim]提示：用 gitsage preferences 可修改个人偏好[/dim]")

    return True
