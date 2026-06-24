"""gitsage CLI - Git-native AI developer workflow assistant."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
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


def _extract_commit_type(message: str) -> str:
    """Extract Conventional Commits type prefix from a message (e.g. 'feat')."""
    import re
    m = re.match(r"^(feat|fix|chore|refactor|docs|test|style|perf|ci|build|revert)[\(:]", message, re.IGNORECASE)
    return m.group(1).lower() if m else ""


def _fire_memory_update(
    repo_name: str,
    message: str,
    category: str,
    branch: str,
    llm: object,
) -> None:
    """Fire-and-forget memory update in a background daemon thread."""
    from .context.memory import update_memory_async
    update_memory_async(
        repo_name=repo_name,
        message=message,
        category=category,
        branch=branch,
        llm_client=llm,  # type: ignore[arg-type]
    )


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
    # Language preamble goes FIRST so the model treats it as a hard requirement.
    # Style hints go after the main prompt (lower priority, advisory).
    from .preferences import load_preferences
    prefs = load_preferences()
    pref_hint = prefs.to_prompt_hint()
    personalised_system = (
        prefs.language_preamble          # ← strong language constraint at top
        + COMMIT_SYSTEM_PROMPT
        + (f"\n\n## Style Preferences\n{pref_hint}" if pref_hint else "")
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
    if resolved_mode == CommitMode.hook:
        # Output only the first candidate message, no formatting — for git hooks
        print(output.candidates[0].message)
        raise typer.Exit(0)

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
        if success:
            _fire_memory_update(
                repo_name=ctx.git_state.repo_name,
                message=message,
                category=_extract_commit_type(message),
                branch=ctx.git_state.branch_name,
                llm=llm,
            )
        raise typer.Exit(0 if success else 1)

    # Interactive (default)
    chosen = show_commit_candidates(output)
    if chosen is None:
        rprint("[yellow]Commit cancelled.[/yellow]")
        raise typer.Exit(0)

    success = execute_git_commit(chosen)
    hook_runner.run(HookEvent.POST_COMMIT)
    if success:
        _fire_memory_update(
            repo_name=ctx.git_state.repo_name,
            message=chosen,
            category=_extract_commit_type(chosen),
            branch=ctx.git_state.branch_name,
            llm=llm,
        )
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
        prefs.language_preamble          # ← language constraint at top
        + STANDUP_SYSTEM_PROMPT
        + (f"\n\n## Style Preferences\n{pref_hint}" if pref_hint else "")
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
        diff=ctx.branch_diff,           # full branch diff, not just staged
        commit_messages=commit_msgs,
        base_branch=base_branch,
        head_branch=ctx.git_state.branch_name,
        ctx_content=ctx.ctx.raw,
    )

    from .preferences import load_preferences
    prefs = load_preferences()
    pref_hint = prefs.to_prompt_hint()
    personalised_pr = (
        prefs.language_preamble
        + PR_SYSTEM_PROMPT
        + (f"\n\n## Style Preferences\n{pref_hint}" if pref_hint else "")
    )

    llm = create_llm_client(cfg.llm)

    try:
        with console.status("[bold green]Generating PR description...[/bold green]"):
            output: PROutput = llm.complete(
                system=personalised_pr,
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
# explain command
# ---------------------------------------------------------------------------

@app.command()
def explain(
    file_path: str = typer.Argument(..., help="File to explain (relative to repo root)"),
    local: bool = typer.Option(False, "--local", help="Skip GitHub API, use local git history only"),
) -> None:
    """Explain why a file's code exists — traces git history to find the story behind the code.

    \b
    Examples:
      gitsage explain src/payment/retry.py
      gitsage explain auth/token.py --local   # no GitHub token needed
    """
    _ensure_consent()
    _ensure_llm_configured()

    from .config import load_config
    from .agent.explain_agent import ExplainAgent
    from .preferences import load_preferences
    from rich.markdown import Markdown
    import os

    cfg = load_config()
    prefs = load_preferences()

    github_token = "" if local else os.environ.get("GITHUB_TOKEN", "")

    try:
        with console.status(f"[bold green]Tracing history of {file_path}...[/bold green]"):
            agent = ExplainAgent.from_config(cfg.llm, github_token=github_token)
            output = agent.explain(file_path, language_preamble=prefs.language_preamble)
    except FileNotFoundError as e:
        rprint(f"[red]File not found:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        from .agent.llm import LLMRateLimitError
        if isinstance(e, LLMRateLimitError):
            rprint(f"[yellow]Rate limit:[/yellow] {e}")
        else:
            rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Display
    confidence_colors = {"high": "green", "medium": "yellow", "low": "red"}
    confidence_icons = {"high": "OK", "medium": "~", "low": "!"}
    color = confidence_colors.get(output.confidence, "white")
    icon = confidence_icons.get(output.confidence, "*")

    console.print()
    console.print(Panel(
        Markdown(output.explanation),
        title=f"[bold]{file_path}[/bold]  [{color}]{icon} {output.confidence} confidence[/{color}]",
        expand=False,
    ))

    if output.sources:
        console.print(f"[dim]Sources: {', '.join(output.sources)}[/dim]")

    if output.local_only:
        console.print("[dim]Configure GITHUB_TOKEN to include PR and Issue context[/dim]")


# ---------------------------------------------------------------------------
# catchup command
# ---------------------------------------------------------------------------

@app.command()
def catchup(
    days: int = typer.Option(0, "--days", "-d", help="Number of days to look back"),
    since: str = typer.Option("", "--since", help="Since a tag (e.g. v1.0.0) or date (YYYY-MM-DD)"),
) -> None:
    """Summarize recent repository changes — what happened while you were away.

    \b
    Examples:
      gitsage catchup             # interactive time range picker
      gitsage catchup --days 7    # past week
      gitsage catchup --days 1    # today only
      gitsage catchup --since v1.2.0   # since a tag
      gitsage catchup --since 2024-03-01  # since a date
    """
    _ensure_consent()
    _ensure_llm_configured()

    from .config import load_config
    from .agent.catchup_agent import CatchupAgent

    # Interactive time picker if no args given
    if not days and not since:
        from rich.prompt import Prompt
        console.print()
        console.print("[bold]查看最近多久的变更？[/bold]\n")
        console.print("  [cyan][1][/cyan] 今天")
        console.print("  [cyan][2][/cyan] 本周（7 天）← 推荐")
        console.print("  [cyan][3][/cyan] 两周")
        console.print("  [cyan][4][/cyan] 自定义天数\n")
        choice = Prompt.ask("选择", choices=["1", "2", "3", "4"], default="2")
        if choice == "1":
            days = 1
        elif choice == "2":
            days = 7
        elif choice == "3":
            days = 14
        else:
            days = int(Prompt.ask("输入天数", default="7"))

    cfg = load_config()
    from .preferences import load_preferences
    prefs = load_preferences()

    try:
        with console.status("[bold green]Analyzing recent changes...[/bold green]"):
            agent = CatchupAgent.from_config(cfg.llm)
            # Parse --since as tag or date
            since_tag = ""
            since_date = ""
            if since:
                if since[0].isdigit() or since.startswith("20"):
                    since_date = since
                else:
                    since_tag = since
            output = agent.catchup(
                days=days or 7,
                since_tag=since_tag,
                since_date=since_date,
                language_preamble=prefs.language_preamble,
            )
    except Exception as e:
        from .agent.llm import LLMRateLimitError
        if isinstance(e, LLMRateLimitError):
            rprint(f"[yellow]Rate limit:[/yellow] {e}")
        else:
            rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Render
    from rich.markdown import Markdown
    console.print()
    console.print(Panel(
        Markdown(output.summary),
        title=f"[bold cyan]变更摘要[/bold cyan] · {output.period_description} · {output.commit_count} commits",
        expand=False,
    ))
    if output.highlights:
        console.print()
        console.print("[bold]亮点：[/bold]")
        for h in output.highlights:
            console.print(f"  • {h}")


# ---------------------------------------------------------------------------
# config sub-commands
# ---------------------------------------------------------------------------

@config_app.command("init")
def config_init() -> None:
    """Analyse git history and generate a personalised CTX.md.

    Phase 1: Scans the last 50 commits locally (no LLM) to detect language,
    emoji usage, commit type conventions, and frequent modules.

    Phase 2: Calls the LLM once to generate a CTX.md draft based on the
    detected patterns, then shows it for your review before saving.
    """
    from .agent.prompts import CONFIG_INIT_SYSTEM_PROMPT, build_config_init_prompt
    from .agent.models import StandupOutput  # reused as plain-text container
    from .agent import create_llm_client
    from rich.syntax import Syntax

    # ── Phase 1: local analysis ───────────────────────────────────────────
    try:
        from .context.git_reader import GitReader
        git_reader = GitReader()
        state = git_reader.get_state(commit_limit=1)
    except Exception as e:
        rprint(f"[red]Not a git repository:[/red] {e}")
        raise typer.Exit(1)

    with console.status("[bold]分析 git 历史...[/bold]"):
        patterns = git_reader.analyze_commit_patterns(limit=50)

    if not patterns:
        rprint("[yellow]没有找到提交记录，将生成通用模板。[/yellow]")

    # Show what was detected
    lang_label = {"zh": "中文", "en": "English", "mixed": "混合"}.get(
        patterns.get("language", "en"), "Unknown"
    )
    console.print()
    console.print(f"[bold]检测到（基于最近 {patterns.get('total_analyzed', 0)} 条 commits）：[/bold]")
    console.print(f"  语言：{lang_label}")
    console.print(f"  Emoji：{'✅ 使用' if patterns.get('uses_emoji') else '❌ 未使用'}")
    console.print(f"  Conventional Commits：{'✅ 使用' if patterns.get('uses_type') else '❌ 未使用'}")
    console.print(f"  Scope：{'✅ 使用' if patterns.get('uses_scope') else '❌ 未使用'}")
    if patterns.get("top_scopes"):
        console.print(f"  常用模块：{', '.join(patterns['top_scopes'])}")
    console.print()

    # ── Phase 2: LLM generation ───────────────────────────────────────────
    try:
        from .config import load_config
        cfg = load_config()
        llm = create_llm_client(cfg.llm)
    except Exception as e:
        rprint(f"[red]LLM 配置错误：{e}[/red]")
        raise typer.Exit(1)

    user_prompt = build_config_init_prompt(
        repo_name=state.repo_name,
        patterns=patterns,
    )

    try:
        with console.status("[bold green]AI 生成 CTX.md 草稿...[/bold green]"):
            result = llm.complete(
                system=CONFIG_INIT_SYSTEM_PROMPT,
                user=user_prompt,
                output_model=StandupOutput,  # only .content is used
            )
        generated_content = result.content.strip()
    except Exception as e:
        from .agent.llm import LLMRateLimitError
        if isinstance(e, LLMRateLimitError):
            rprint(f"[yellow]⚠️ 限速：{e}[/yellow]")
        else:
            rprint(f"[red]LLM 错误：{e}[/red]")
        rprint("[dim]将生成通用模板代替。[/dim]")
        generated_content = _default_ctx_template(state.repo_name)

    # ── Phase 3: user confirmation ────────────────────────────────────────
    console.print("[bold]生成的 CTX.md 内容：[/bold]\n")
    console.print(Syntax(generated_content, "markdown", theme="github-dark", word_wrap=True))
    console.print()

    ctx_path = Path.cwd() / "CTX.md"
    if ctx_path.exists():
        if not Confirm.ask("CTX.md 已存在，覆盖？", default=False):
            raise typer.Exit(0)

    action = Prompt.ask(
        "操作",
        choices=["s", "e", "q"],
        default="s",
        show_choices=False,
    )
    console.print("  [dim][s] 直接保存  [e] 在编辑器里修改后保存  [q] 放弃[/dim]")
    action = Prompt.ask("请输入", choices=["s", "e", "q"], default="s")

    if action == "q":
        rprint("[dim]已放弃。[/dim]")
        raise typer.Exit(0)

    if action == "e":
        import subprocess, tempfile, os
        editor = os.environ.get("EDITOR", "nano")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(generated_content)
            tmp = f.name
        subprocess.run([editor, tmp])
        with open(tmp, encoding="utf-8") as f:
            generated_content = f.read()
        os.unlink(tmp)

    ctx_path.write_text(generated_content, encoding="utf-8")
    rprint(f"\n[green]✅ CTX.md 已保存到 {ctx_path}[/green]")
    rprint("[dim]提示：把它提交到 git，团队成员也能享受个性化输出。[/dim]")


def _default_ctx_template(repo_name: str) -> str:
    """Fallback generic CTX.md when LLM is unavailable."""
    return f"""# {repo_name} — Project Context

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
"""


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
        ("openai-compatible", "deepseek-v4-flash", "DeepSeek — https://platform.deepseek.com"),
        ("openai-compatible", "any-model-name", "任意 OpenAI-compatible 接口：配置 base_url 即可"),
        ("openai", "gpt-4o / gpt-4o-mini", "OpenAI — https://platform.openai.com"),
        ("anthropic", "claude-sonnet-4-6", "Anthropic — 需另装 anthropic 包"),
        ("ollama", "qwen2.5:14b / llama3", "本地模型，完全离线 — https://ollama.com"),
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
# mcp commands
# ---------------------------------------------------------------------------

mcp_app = typer.Typer(help="MCP Server management.")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the gitsage MCP server (stdio transport).

    Use this to connect gitsage to Claude Desktop, Cursor, or any MCP client.
    Configure your MCP client to run: gitsage mcp serve
    """
    from .mcp import run_server, MCP_AVAILABLE
    import asyncio

    if not MCP_AVAILABLE:
        rprint("[red]Error:[/red] mcp package not installed.")
        rprint("Run: pip install mcp")
        raise typer.Exit(1)

    # Print to stderr so the message doesn't interfere with JSON-RPC on stdout
    Console(stderr=True).print("[dim]gitsage MCP server starting on stdio...[/dim]")
    asyncio.run(run_server())


@mcp_app.command("install")
def mcp_install(
    client: str = typer.Option("claude", "--client", "-c",
                                help="MCP client: claude | cursor | generic"),
) -> None:
    """Register gitsage MCP server with an MCP client (e.g. Claude Desktop).

    \b
    Examples:
      gitsage mcp install                  # Claude Desktop (default)
      gitsage mcp install --client cursor  # Cursor IDE
    """
    import sys
    import json as _json

    gitsage_bin = Path(sys.executable).parent / "gitsage"
    if not gitsage_bin.exists():
        gitsage_bin = Path(sys.executable).parent / "gitsage.exe"

    server_config = {
        "command": str(gitsage_bin),
        "args": ["mcp", "serve"],
    }

    if client == "claude":
        # Claude Desktop config
        config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if not config_path.parent.exists():
            # Try Linux path
            config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

        _update_json_config(config_path, "mcpServers", "gitsage", server_config)
        rprint(f"[green]Registered with Claude Desktop[/green]")
        rprint(f"   Config: {config_path}")
        rprint()
        rprint("[bold]Next steps:[/bold]")
        rprint("  1. Restart Claude Desktop")
        rprint("  2. You should see 'gitsage' in the MCP tools list")
        rprint("  3. Ask Claude: 'What's in my staged diff?' or 'Show recent commits'")

    elif client == "cursor":
        config_path = Path.cwd() / ".cursor" / "mcp.json"
        config_path.parent.mkdir(exist_ok=True)
        _update_json_config(config_path, "mcpServers", "gitsage", server_config)
        rprint(f"[green]Registered with Cursor[/green]")
        rprint(f"   Config: {config_path}")

    else:
        # Generic: just print the config
        rprint("[bold]MCP Server Configuration:[/bold]")
        rprint(_json.dumps({"mcpServers": {"gitsage": server_config}}, indent=2))
        rprint()
        rprint("Add the above to your MCP client's configuration file.")


def _update_json_config(path: Path, section: str, key: str, value: dict) -> None:
    """Update a JSON config file, creating it if needed."""
    import json as _json
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = _json.loads(path.read_text())
        except Exception:
            data = {}
    if section not in data:
        data[section] = {}
    data[section][key] = value
    path.write_text(_json.dumps(data, indent=2))


@mcp_app.command("status")
def mcp_status() -> None:
    """Check MCP server availability and show configuration."""
    from .mcp import MCP_AVAILABLE
    import sys

    rprint(f"[bold]gitsage MCP Server[/bold]")
    rprint(f"  mcp package: {'[green]installed[/green]' if MCP_AVAILABLE else '[red]not installed[/red]'}")

    gitsage_bin = Path(sys.executable).parent / "gitsage"
    rprint(f"  gitsage binary: {gitsage_bin}")

    rprint()
    rprint("[bold]To connect Claude Desktop:[/bold]")
    rprint("  gitsage mcp install")
    rprint()
    rprint("[bold]Manual config (add to claude_desktop_config.json):[/bold]")
    config = {
        "mcpServers": {
            "gitsage": {
                "command": str(gitsage_bin),
                "args": ["mcp", "serve"],
            }
        }
    }
    import json as _json
    rprint(_json.dumps(config, indent=2))


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

# Generate commit message (mode=hook outputs only the best candidate, no formatting)
GENERATED=$("$GITSAGE" commit --mode hook 2>/dev/null)

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
