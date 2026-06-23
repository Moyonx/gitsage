"""gitsage CLI - Git-native AI developer workflow assistant."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich import print as rprint

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="gitsage",
    help="Git-native AI developer workflow assistant.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

config_app = typer.Typer(help="Manage gitsage configuration.")
model_app = typer.Typer(help="Manage LLM model settings.")
memory_app = typer.Typer(help="Manage persistent memory.")
skill_app = typer.Typer(help="Manage skills.")

app.add_typer(config_app, name="config")
app.add_typer(model_app, name="model")
app.add_typer(memory_app, name="memory")
app.add_typer(skill_app, name="skill")

console = Console()

VERSION = "0.1.0"

PRIVACY_NOTICE = """[bold cyan]gitsage Privacy Notice[/bold cyan]

gitsage sends your git diff and commit history to an LLM provider (e.g. DeepSeek, OpenAI, Anthropic).

[yellow]What is sent:[/yellow] staged diffs, recent commit messages, branch name, CTX.md content
[yellow]What is NOT sent:[/yellow] file contents outside the diff, credentials, secrets

By continuing you consent to this. Your consent is saved to ~/.gitsage/config.yml.
"""

GLOBAL_CONFIG_DIR = Path.home() / ".gitsage"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yml"


# ---------------------------------------------------------------------------
# Privacy consent helpers
# ---------------------------------------------------------------------------

def _has_consented() -> bool:
    """Return True if the user has already given privacy consent."""
    if not GLOBAL_CONFIG_FILE.exists():
        return False
    try:
        import yaml
        data = yaml.safe_load(GLOBAL_CONFIG_FILE.read_text()) or {}
        return bool(data.get("privacy_consent", False))
    except Exception:
        return False


def _save_consent() -> None:
    """Save privacy consent flag to global config."""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    import yaml
    data: dict = {}
    if GLOBAL_CONFIG_FILE.exists():
        try:
            data = yaml.safe_load(GLOBAL_CONFIG_FILE.read_text()) or {}
        except Exception:
            data = {}
    data["privacy_consent"] = True
    GLOBAL_CONFIG_FILE.write_text(yaml.dump(data))


def _ensure_consent() -> None:
    """Show privacy notice on first run and prompt for consent."""
    if _has_consented():
        return
    console.print(Panel(PRIVACY_NOTICE, expand=False))
    confirmed = typer.confirm("Do you consent to sending data to the LLM provider?", default=True)
    if not confirmed:
        rprint("[red]Consent declined. gitsage will not run without consent.[/red]")
        raise typer.Exit(1)
    _save_consent()
    console.print("[green]Consent saved. You will not be asked again.[/green]\n")


def _ensure_llm_configured() -> None:
    """If no LLM is configured, launch the setup wizard and exit on cancel."""
    from .wizard import is_llm_configured, run_setup_wizard
    if is_llm_configured():
        return
    # First run: show guided setup
    ok = run_setup_wizard(skip_banner=False)
    if not ok:
        raise typer.Exit(0)


# ---------------------------------------------------------------------------
# Token estimate helper
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# commit command
# ---------------------------------------------------------------------------

@app.command()
def commit(
    mode: Optional[str] = typer.Option(
        None,
        "--mode", "-m",
        help="Output mode: interactive | print | execute",
    ),
    estimate: bool = typer.Option(
        False,
        "--estimate",
        help="Show token count estimate and exit without calling LLM.",
    ),
) -> None:
    """Generate a commit message for staged changes."""
    _ensure_consent()
    _ensure_llm_configured()

    from .config import load_config, CommitMode
    from .context import ContextBuilder
    from .agent import create_llm_client, build_commit_user_prompt, CommitOutput
    from .agent.prompts import COMMIT_SYSTEM_PROMPT
    from .harness import QualityGate, DeterministicOverride
    from .harness.hooks import HookRunner, HookEvent
    from .skills import SkillLoader
    from .renderer import show_commit_candidates, execute_git_commit

    cfg = load_config()

    # Resolve mode
    try:
        resolved_mode = CommitMode(mode) if mode else cfg.commit.default_mode
    except ValueError:
        rprint(f"[red]Invalid mode '{mode}'. Choose: interactive, print, execute[/red]")
        raise typer.Exit(1)

    # Build context
    try:
        builder = ContextBuilder()
    except ValueError as e:
        rprint(f"[red]Not a git repository: {e}[/red]")
        raise typer.Exit(1)

    # Load skill
    skill_loader = SkillLoader()
    skill = skill_loader.load("commit")
    skill_content = skill.content if skill else ""

    ctx = builder.build_commit_context(skill_content=skill_content)

    # Check for staged files
    if ctx.git_state.is_clean:
        rprint("[yellow]No staged files found. Stage your changes first with:[/yellow]")
        rprint("  [bold]git add <files>[/bold]")
        raise typer.Exit(0)

    # Build user prompt
    recent_msgs = [c.message for c in ctx.git_state.recent_commits]
    user_prompt = build_commit_user_prompt(
        diff=ctx.git_state.staged_diff,
        recent_commits=recent_msgs,
        branch_name=ctx.git_state.branch_name,
        ctx_content=ctx.ctx.raw,
        memory_content=ctx.memory_content,
        skill_content=ctx.skill_content,
    )

    # Token estimate
    if estimate:
        system_prompt = COMMIT_SYSTEM_PROMPT
        total = _estimate_tokens(system_prompt + user_prompt)
        rprint(f"[cyan]Estimated tokens:[/cyan] ~{total:,}")
        rprint(f"[dim]Staged files: {len(ctx.git_state.staged_files)} | Diff lines: {len(ctx.git_state.staged_diff.splitlines())}[/dim]")
        raise typer.Exit(0)

    # Pre-commit hook
    hook_runner = HookRunner()
    hook_runner.run(HookEvent.PRE_COMMIT)

    # Load user preferences and build personalised system prompt
    from .preferences import load_preferences
    prefs = load_preferences()
    pref_hint = prefs.to_prompt_hint()
    personalised_system = (
        COMMIT_SYSTEM_PROMPT
        + (f"\n\n## User Preferences\n{pref_hint}" if pref_hint else "")
    )

    # Call LLM
    llm = create_llm_client(cfg.llm)
    gate = QualityGate.for_commit()
    override = DeterministicOverride(cfg.rules, branch_name=ctx.git_state.branch_name)

    try:
        with console.status("[bold green]Generating commit message...[/bold green]"):
            output: CommitOutput = llm.complete(
                system=personalised_system,
                user=user_prompt,
                output_model=CommitOutput,
            )
    except Exception as e:
        from .agent.llm import LLMRateLimitError
        if isinstance(e, LLMRateLimitError):
            rprint(f"\n[yellow]⚠️  Rate limit reached:[/yellow] {e}")
            rprint("[dim]请稍等片刻后重试（通常等待 60 秒）[/dim]")
        else:
            rprint(f"\n[red]LLM error:[/red] {e}")
        rprint("\n[yellow]Graceful degradation:[/yellow] Here is your diff for manual review:")
        rprint(f"[dim]{ctx.git_state.staged_summary}[/dim]")
        rprint("\nTip: Add a [bold]CTX.md[/bold] to your repo to improve future suggestions.")
        raise typer.Exit(1)

    # Apply quality gate and override to each candidate
    for candidate in output.candidates:
        gate_result = gate.check(candidate.message)
        if not gate_result.passed:
            rprint(f"[dim]Quality gate: {gate_result.message}[/dim]")
        candidate.message = override.apply_to_commit(candidate.message)

    # Dispatch by mode
    if resolved_mode == CommitMode.print:
        for i, c in enumerate(output.candidates, 1):
            console.print(f"[bold][{i}][/bold] {c.message}")
            console.print(f"    [dim]{c.reason}[/dim]")
        raise typer.Exit(0)

    if resolved_mode == CommitMode.execute:
        message = output.candidates[0].message
        rprint(f"[bold]Committing:[/bold] {message}")
        success = execute_git_commit(message)
        hook_runner.run(HookEvent.POST_COMMIT)
        raise typer.Exit(0 if success else 1)

    # Interactive (default)
    chosen = show_commit_candidates(output)
    if chosen is None:
        rprint("[yellow]Commit cancelled.[/yellow]")
        raise typer.Exit(0)

    success = execute_git_commit(chosen)
    hook_runner.run(HookEvent.POST_COMMIT)
    raise typer.Exit(0 if success else 1)


# ---------------------------------------------------------------------------
# standup command
# ---------------------------------------------------------------------------

@app.command()
def standup(
    print_only: bool = typer.Option(
        False,
        "--print",
        help="Print standup text to stdout instead of interactive display.",
    ),
    estimate: bool = typer.Option(
        False,
        "--estimate",
        help="Show token count estimate and exit.",
    ),
) -> None:
    """Generate a standup report from today's commits."""
    _ensure_consent()
    _ensure_llm_configured()

    from .config import load_config
    from .context import ContextBuilder
    from .agent import create_llm_client, build_standup_user_prompt, StandupOutput
    from .agent.prompts import STANDUP_SYSTEM_PROMPT
    from .harness.hooks import HookRunner, HookEvent
    from .skills import SkillLoader
    from .renderer import show_standup

    cfg = load_config()

    try:
        builder = ContextBuilder()
    except ValueError as e:
        rprint(f"[red]Not a git repository: {e}[/red]")
        raise typer.Exit(1)

    skill_loader = SkillLoader()
    skill = skill_loader.load("standup")
    skill_content = skill.content if skill else ""

    ctx = builder.build_standup_context(skill_content=skill_content)

    commits_data = [
        {
            "sha": c.sha,
            "message": c.message,
            "author": c.author,
            "timestamp": c.date.strftime("%H:%M"),
        }
        for c in ctx.git_state.today_commits
    ]

    user_prompt = build_standup_user_prompt(
        commits=commits_data,
        date_str=ctx.date_str,
        ctx_content=ctx.ctx.raw,
        memory_content=ctx.memory_content,
        skill_content=ctx.skill_content,
    )

    if estimate:
        total = _estimate_tokens(STANDUP_SYSTEM_PROMPT + user_prompt)
        rprint(f"[cyan]Estimated tokens:[/cyan] ~{total:,}")
        rprint(f"[dim]Today's commits: {len(commits_data)}[/dim]")
        raise typer.Exit(0)

    hook_runner = HookRunner()
    hook_runner.run(HookEvent.PRE_STANDUP)

    from .preferences import load_preferences
    prefs = load_preferences()
    pref_hint = prefs.to_prompt_hint()
    personalised_standup = (
        STANDUP_SYSTEM_PROMPT
        + (f"\n\n## User Preferences\n{pref_hint}" if pref_hint else "")
    )

    llm = create_llm_client(cfg.llm)

    try:
        with console.status("[bold green]Generating standup...[/bold green]"):
            output: StandupOutput = llm.complete(
                system=personalised_standup,
                user=user_prompt,
                output_model=StandupOutput,
            )
    except Exception as e:
        rprint(f"\n[red]LLM error:[/red] {e}")
        rprint("\n[yellow]Graceful degradation:[/yellow] Here are today's commits:")
        for c in ctx.git_state.today_commits:
            rprint(f"  [dim]{c.short_sha}[/dim] {c.message}")
        raise typer.Exit(1)

    hook_runner.run(HookEvent.POST_STANDUP)

    if print_only:
        print(output.content)
    else:
        show_standup(output.content)


# ---------------------------------------------------------------------------
# pr command
# ---------------------------------------------------------------------------

@app.command()
def pr(
    base_branch: str = typer.Option(
        "main",
        "--base-branch", "-b",
        help="Base branch to compare against.",
    ),
) -> None:
    """Generate a PR title and description for the current branch."""
    _ensure_consent()
    _ensure_llm_configured()

    from .config import load_config
    from .context import ContextBuilder
    from .agent import create_llm_client, build_pr_user_prompt, PROutput
    from .agent.prompts import PR_SYSTEM_PROMPT
    from .renderer import show_pr

    cfg = load_config()

    try:
        builder = ContextBuilder()
    except ValueError as e:
        rprint(f"[red]Not a git repository: {e}[/red]")
        raise typer.Exit(1)

    ctx = builder.build_pr_context(base_branch=base_branch)
    commit_msgs = [c.message for c in ctx.git_state.recent_commits]

    user_prompt = build_pr_user_prompt(
        diff=ctx.git_state.staged_diff,
        commit_messages=commit_msgs,
        base_branch=base_branch,
        head_branch=ctx.git_state.branch_name,
        ctx_content=ctx.ctx.raw,
    )

    llm = create_llm_client(cfg.llm)

    try:
        with console.status("[bold green]Generating PR description...[/bold green]"):
            output: PROutput = llm.complete(
                system=PR_SYSTEM_PROMPT,
                user=user_prompt,
                output_model=PROutput,
            )
    except Exception as e:
        rprint(f"\n[red]LLM error:[/red] {e}")
        raise typer.Exit(1)

    show_pr(output.title, output.description)

    if output.breaking_changes:
        rprint("\n[bold red]Breaking changes:[/bold red]")
        for change in output.breaking_changes:
            rprint(f"  - {change}")


# ---------------------------------------------------------------------------
# config sub-commands
# ---------------------------------------------------------------------------

@config_app.command("init")
def config_init() -> None:
    """Analyze git history and generate a CTX.md template."""
    try:
        from .context import GitReader
        git = GitReader()
        state = git.get_state()
    except Exception as e:
        rprint(f"[red]Error reading git state: {e}[/red]")
        raise typer.Exit(1)

    ctx_path = Path.cwd() / "CTX.md"
    if ctx_path.exists():
        overwrite = typer.confirm("CTX.md already exists. Overwrite?", default=False)
        if not overwrite:
            raise typer.Exit(0)

    # Generate a template based on discovered info
    branch = state.branch_name
    repo = state.repo_name
    template = f"""# {repo} — Project Context

## Project Background

Describe your project here. What does it do? What is the tech stack?

## Commit Rules

- Use Conventional Commits format: <type>(<scope>): <description>
- Keep subject line under 72 characters
- Write in imperative mood

## Standup Format

- What I did yesterday
- What I'm doing today
- Any blockers

## Rules

always:
  - Use imperative mood in commit messages

never:
  - Include file paths in commit messages
  - Include binary file changes in commit messages
"""

    ctx_path.write_text(template)
    rprint(f"[green]CTX.md created at {ctx_path}[/green]")
    rprint("[dim]Edit it to reflect your project's conventions.[/dim]")


@config_app.command("show")
def config_show() -> None:
    """Show the resolved gitsage configuration."""
    from .config import load_config
    cfg = load_config()

    table = Table(title="Resolved Configuration", show_header=True, header_style="bold cyan")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("llm.provider", cfg.llm.provider)
    table.add_row("llm.model", cfg.llm.model)
    table.add_row("llm.api_key", "***" if cfg.llm.api_key else "[red](not set)[/red]")
    table.add_row("llm.base_url", cfg.llm.base_url or "[dim](default)[/dim]")
    table.add_row("commit.default_mode", cfg.commit.default_mode.value)
    table.add_row("commit.max_candidates", str(cfg.commit.max_candidates))
    table.add_row("commit.max_retries", str(cfg.commit.max_retries))
    table.add_row("rules.always", "\n".join(cfg.rules.always) or "[dim](none)[/dim]")
    table.add_row("rules.never", "\n".join(cfg.rules.never) or "[dim](none)[/dim]")

    console.print(table)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key (e.g. llm.model)"),
    value: str = typer.Argument(..., help="Config value"),
) -> None:
    """Set a configuration value in ~/.gitsage/config.yml."""
    import yaml

    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if GLOBAL_CONFIG_FILE.exists():
        try:
            data = yaml.safe_load(GLOBAL_CONFIG_FILE.read_text()) or {}
        except Exception:
            data = {}

    # Nested key support: llm.model -> data["llm"]["model"]
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value

    GLOBAL_CONFIG_FILE.write_text(yaml.dump(data))
    rprint(f"[green]Set {key} = {value}[/green]")


# ---------------------------------------------------------------------------
# model sub-commands
# ---------------------------------------------------------------------------

KNOWN_MODELS = {
    "deepseek": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    "anthropic": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"],
    "ollama": ["llama3", "mistral", "codellama"],
}


@model_app.command("list")
def model_list() -> None:
    """Show the currently configured model and common model suggestions."""
    from .config import load_config

    cfg = load_config()

    # ── Active model (from config) ────────────────────────────────────────────
    console.print()
    console.print("[bold cyan]当前配置的模型[/bold cyan]")

    active_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    active_table.add_column("Provider")
    active_table.add_column("Model")
    active_table.add_column("Base URL")
    active_table.add_column("API Key")

    key_status = "[green]✅ 已配置[/green]" if cfg.llm.api_key else "[red]❌ 未配置[/red]"
    active_table.add_row(
        f"[bold green]{cfg.llm.provider}[/bold green]",
        f"[bold green]{cfg.llm.model}[/bold green]",
        cfg.llm.base_url or "[dim]（SDK 自动处理）[/dim]",
        key_status,
    )
    console.print(active_table)

    # ── Common model suggestions ──────────────────────────────────────────────
    console.print()
    console.print("[dim]常用模型参考（用 gitsage model set 切换）[/dim]")

    suggest_table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
    suggest_table.add_column("Provider", style="dim")
    suggest_table.add_column("Model", style="dim")
    suggest_table.add_column("说明", style="dim")

    SUGGESTIONS = [
        ("openai-compatible", "gpt-5.4 / gpt-5.5", "美团内网 AIGC 接口"),
        ("openai-compatible", "deepseek-v4-flash", "DeepSeek 官方接口，需配 base_url"),
        ("openai", "gpt-4o / gpt-4o-mini", "OpenAI 官方"),
        ("anthropic", "claude-sonnet-4-6", "Anthropic，需单独安装 anthropic 包"),
        ("ollama", "qwen2.5:14b / llama3", "本地模型，需先安装 Ollama"),
    ]

    for provider, model, note in SUGGESTIONS:
        suggest_table.add_row(provider, model, note)

    console.print(suggest_table)
    console.print()
    console.print("[dim]切换示例: gitsage model set gpt-5.5[/dim]")
    console.print("[dim]查看配置: gitsage config show[/dim]")


@model_app.command("set")
def model_set(
    provider_model: str = typer.Argument(
        ..., help="Provider/model string, e.g. deepseek/deepseek-v4-flash"
    ),
) -> None:
    """Set the default LLM model."""
    if "/" not in provider_model:
        rprint("[red]Format must be PROVIDER/MODEL, e.g. openai/gpt-4o[/red]")
        raise typer.Exit(1)

    provider, model_name = provider_model.split("/", 1)

    import yaml
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if GLOBAL_CONFIG_FILE.exists():
        try:
            data = yaml.safe_load(GLOBAL_CONFIG_FILE.read_text()) or {}
        except Exception:
            data = {}

    data.setdefault("llm", {})
    data["llm"]["provider"] = provider
    data["llm"]["model"] = model_name
    GLOBAL_CONFIG_FILE.write_text(yaml.dump(data))

    rprint(f"[green]Model set to {provider}/{model_name}[/green]")
    rprint(f"[dim]Make sure {provider.upper()}_API_KEY is set in your environment.[/dim]")


@model_app.command("test")
def model_test() -> None:
    """Test the LLM connection with a simple ping."""
    from .config import load_config
    from .agent import create_llm_client, CommitOutput

    cfg = load_config()
    rprint(f"Testing connection to [bold]{cfg.llm.provider}/{cfg.llm.model}[/bold]...")

    llm = create_llm_client(cfg.llm)
    try:
        with console.status("[bold green]Calling LLM...[/bold green]"):
            result = llm.complete(
                system="You are a test assistant. Respond with a single valid JSON object.",
                user="Generate a simple test commit message for a 'hello world' change.",
                output_model=CommitOutput,
            )
        rprint(f"[green]Connection OK.[/green] Sample output: {result.candidates[0].message}")
    except Exception as e:
        rprint(f"[red]Connection failed:[/red] {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# memory sub-commands
# ---------------------------------------------------------------------------

@memory_app.command("show")
def memory_show() -> None:
    """Show current memory for this repository."""
    try:
        from .context import GitReader
        from .context.memory import MemoryManager
        git = GitReader()
        state = git.get_state()
        memory = MemoryManager(state.repo_name)
        content = memory.read()
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not content:
        rprint("[dim]No memory stored for this repository.[/dim]")
        return

    console.print(Panel(content, title="[bold cyan]Memory[/bold cyan]", expand=False))


@memory_app.command("clear")
def memory_clear() -> None:
    """Clear memory for this repository."""
    try:
        from .context import GitReader
        from .context.memory import MemoryManager
        git = GitReader()
        state = git.get_state()
        memory = MemoryManager(state.repo_name)
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    confirmed = typer.confirm("Clear all memory for this repository?", default=False)
    if not confirmed:
        raise typer.Exit(0)

    memory.clear()
    rprint("[green]Memory cleared.[/green]")


# ---------------------------------------------------------------------------
# skill sub-commands
# ---------------------------------------------------------------------------

@skill_app.command("list")
def skill_list() -> None:
    """List all available skills."""
    from .skills import SkillLoader

    loader = SkillLoader()
    skills = loader.load_all()

    if not skills:
        rprint("[dim]No skills found.[/dim]")
        rprint(f"[dim]Add skills to .gitsage/skills/<name>/SKILL.md or ~/.gitsage/skills/<name>/SKILL.md[/dim]")
        return

    table = Table(title="Available Skills", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Trigger")
    table.add_column("Description")
    table.add_column("Source")

    for skill in skills:
        source = "project" if ".gitsage/skills" in str(skill.path) else "global"
        table.add_row(skill.name, skill.trigger, skill.description or "[dim](none)[/dim]", source)

    console.print(table)


# ---------------------------------------------------------------------------
# setup command
# ---------------------------------------------------------------------------

@app.command()
def setup() -> None:
    """Interactive setup wizard — configure your LLM provider.

    Guides you through choosing a provider (Ollama, DeepSeek, Anthropic, OpenAI,
    or a custom endpoint) and confirming the three parameters:
    api_key, base_url, and model.
    """
    from .wizard import run_setup_wizard
    run_setup_wizard(skip_banner=False)


@app.command()
def preferences(
    reset: bool = typer.Option(False, "--reset", help="Clear all preferences and start over."),
    show: bool = typer.Option(False, "--show", help="Show current preferences without editing."),
) -> None:
    """Set or view personal preferences (language, commit style, standup format…).

    \b
    Examples:
      gitsage preferences          # Edit preferences interactively
      gitsage preferences --show   # View current preferences
      gitsage preferences --reset  # Clear and reconfigure
    """
    from .preferences import (
        load_preferences, save_preferences,
        run_preferences_survey, has_preferences,
        _show_preferences_summary,
    )

    if reset:
        if Confirm.ask("清除所有偏好设置并重新配置？", default=False):
            prefs = run_preferences_survey(skip_banner=False)
        else:
            raise typer.Exit(0)
        return

    if show:
        if has_preferences():
            prefs = load_preferences()
            _show_preferences_summary(prefs)
        else:
            rprint("[yellow]尚未设置偏好。运行 gitsage preferences 进行配置。[/yellow]")
        return

    # Default: run survey (respects skip if already set)
    if has_preferences():
        console.print()
        rprint("[dim]当前已有偏好设置（用 --show 查看，--reset 重置）[/dim]")
        if not Confirm.ask("重新配置偏好？", default=False):
            raise typer.Exit(0)

    run_preferences_survey(skip_banner=False)


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------

@app.command()
def doctor() -> None:
    """Check environment and configuration health."""
    import os
    import shutil

    rprint("[bold cyan]gitsage doctor[/bold cyan]\n")

    checks: list[tuple[str, bool, str]] = []

    # Python version
    py_ok = sys.version_info >= (3, 11)
    checks.append(("Python >= 3.11", py_ok, f"Python {sys.version.split()[0]}"))

    # git binary
    git_ok = shutil.which("git") is not None
    checks.append(("git binary", git_ok, shutil.which("git") or "not found"))

    # In a git repo?
    try:
        from .context import GitReader
        gr = GitReader()
        state = gr.get_state()
        repo_ok = True
        repo_msg = state.repo_name
    except Exception as e:
        repo_ok = False
        repo_msg = str(e)
    checks.append(("git repository", repo_ok, repo_msg))

    # Config file
    cfg_ok = GLOBAL_CONFIG_FILE.exists()
    checks.append(("~/.gitsage/config.yml", cfg_ok, str(GLOBAL_CONFIG_FILE) if cfg_ok else "not found"))

    # API key
    from .config import load_config, PROVIDER_ENV_VARS
    cfg = load_config()
    env_var = PROVIDER_ENV_VARS.get(cfg.llm.provider, "")
    api_key_ok = bool(cfg.llm.api_key)
    checks.append((f"{env_var or 'API key'}", api_key_ok, "set" if api_key_ok else "missing"))

    # CTX.md
    try:
        from .context.ctx_reader import CTXReader
        ctx_reader = CTXReader()
        ctx_path = ctx_reader.find_ctx_file()
        ctx_ok = ctx_path is not None
        ctx_msg = str(ctx_path) if ctx_path else "not found (optional)"
    except Exception:
        ctx_ok = False
        ctx_msg = "error"
    checks.append(("CTX.md", ctx_ok, ctx_msg))

    # Privacy consent
    consent_ok = _has_consented()
    checks.append(("Privacy consent", consent_ok, "given" if consent_ok else "not given (run any command)"))

    # Print results
    for label, ok, detail in checks:
        icon = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        rprint(f"  {icon}  {label:30s} {detail}")

    all_ok = all(ok for _, ok, _ in checks[:5])  # first 5 are critical
    console.print()
    if all_ok:
        rprint("[green]All critical checks passed.[/green]")
    else:
        rprint("[yellow]Some checks failed. Fix the issues above.[/yellow]")


# ---------------------------------------------------------------------------
# install-hooks command
# ---------------------------------------------------------------------------

@app.command("install-hooks")
def install_hooks() -> None:
    """Install gitsage git hooks into .git/hooks/."""
    import shutil

    hooks_dir = Path.cwd() / ".git" / "hooks"
    if not hooks_dir.exists():
        rprint("[red].git/hooks directory not found. Are you in a git repo?[/red]")
        raise typer.Exit(1)

    # Detect the gitsage binary path so the hook works even outside the venv
    gitsage_bin = shutil.which("gitsage") or sys.executable.replace("python", "gitsage")
    # Prefer the binary next to the current Python interpreter (same venv)
    venv_gitsage = Path(sys.executable).parent / "gitsage"
    if venv_gitsage.exists():
        gitsage_bin = str(venv_gitsage)

    hook_content = f"""#!/bin/bash
# gitsage prepare-commit-msg hook
# Automatically generates a commit message with AI when you run `git commit`.
#
# How it works:
#   1. gitsage generates a message from your staged diff
#   2. The message is pre-filled in the editor
#   3. You review / edit / save → commit happens
#
# To disable: delete .git/hooks/prepare-commit-msg

COMMIT_MSG_FILE="$1"
COMMIT_SOURCE="$2"   # "message" when -m is used, "merge" for merges, etc.

# Only auto-generate for fresh commits (skip if -m, --amend, merge, squash)
if [ -n "$COMMIT_SOURCE" ]; then
    exit 0
fi

# gitsage binary path (detected at install time)
GITSAGE="{gitsage_bin}"

if [ ! -x "$GITSAGE" ]; then
    exit 0
fi

# Generate commit message (mode=print outputs the best candidate to stdout)
GENERATED=$("$GITSAGE" commit --mode print 2>/dev/null)

if [ $? -eq 0 ] && [ -n "$GENERATED" ]; then
    # Write generated message to the file git is waiting for
    printf '%s\\n' "$GENERATED" > "$COMMIT_MSG_FILE"
fi
"""
    hook_path = hooks_dir / "prepare-commit-msg"
    if hook_path.exists():
        if not Confirm.ask("prepare-commit-msg hook already exists. Overwrite?", default=False):
            raise typer.Exit(0)

    hook_path.write_text(hook_content)
    hook_path.chmod(0o755)
    rprint(f"[green]✅ Hook installed: {hook_path}[/green]")
    rprint()
    rprint("[bold]使用方法：[/bold]")
    rprint("  git add <文件>")
    rprint("  git commit          ← gitsage 自动生成消息并在编辑器里预填")
    rprint("  [dim]保存退出编辑器 → 提交完成[/dim]")
    rprint()
    rprint("[dim]提示：git commit -m '...' 时不会触发 AI 生成（已有消息则跳过）[/dim]")


# ---------------------------------------------------------------------------
# install-completion command
# ---------------------------------------------------------------------------

@app.command("install-completion")
def install_completion(
    shell: Optional[str] = typer.Argument(
        None,
        help="Shell type: bash, zsh, fish, powershell. Auto-detected if omitted.",
    ),
) -> None:
    """Install shell completion for gitsage."""
    import os
    detected = shell or os.environ.get("SHELL", "bash").split("/")[-1]
    rprint(f"[cyan]Detected shell:[/cyan] {detected}")
    rprint("\nTo enable completion, add this to your shell profile:")
    if detected == "zsh":
        rprint('[dim]  eval "$(gitsage --show-completion zsh)"[/dim]')
    elif detected == "fish":
        rprint("[dim]  gitsage --show-completion fish | source[/dim]")
    else:
        rprint('[dim]  eval "$(gitsage --show-completion bash)"[/dim]')
    rprint("\n[dim]Or run: typer gitsage.cli utils install-completion[/dim]")


# ---------------------------------------------------------------------------
# version callback
# ---------------------------------------------------------------------------

def _version_callback(value: bool) -> None:
    if value:
        rprint(f"gitsage version [bold]{VERSION}[/bold]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version", "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """gitsage - Git-native AI developer workflow assistant."""
