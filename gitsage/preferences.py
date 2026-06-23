"""User preference onboarding for gitsage.

Runs once after LLM setup, collects a handful of questions,
and saves answers to ~/.gitsage/config.yml under the `preferences` key.

Preferences are then injected into every LLM prompt to personalise output.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich import print as rprint

console = Console()

GLOBAL_CONFIG_DIR = Path.home() / ".gitsage"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yml"


# ── Preferences data model ────────────────────────────────────────────────────

class UserPreferences(BaseModel):
    """Persisted user preferences that personalise gitsage output."""

    # Language
    language: Literal["zh", "en", "auto"] = "auto"

    # Commit style
    commit_emoji: bool = False
    commit_scope: bool = True          # feat(payment): xxx  vs  feat: xxx
    commit_length: Literal["brief", "standard", "detailed"] = "standard"

    # Ticket / issue tracking
    ticket_format: Literal["none", "jira", "github", "auto"] = "auto"
    ticket_pattern: str = ""           # e.g. "PAY", "PROJ" for JIRA prefix

    # Standup
    standup_audience: Literal["technical", "nontechnical"] = "technical"
    standup_format: Literal["bullets", "paragraph"] = "bullets"

    @property
    def language_preamble(self) -> str:
        """Strong language instruction — must go at the TOP of the system prompt.

        LLMs give higher weight to instructions at the beginning. Appending at
        the end (as a style hint) is not reliable for overriding the model's
        default language.
        """
        if self.language == "zh":
            return (
                "【强制语言要求】用户偏好中文输出。\n"
                "在 JSON 输出中，所有 `message` 字段的描述部分必须使用中文（简体）。\n"
                "类型前缀（feat/fix/chore 等）保持英文，冒号后的描述文字必须是中文。\n"
                "正确示例：\n"
                "  \"message\": \"feat(payment): 新增支付重试机制，支持指数退避\"\n"
                "  \"message\": \"fix: 修复用户登录超时的问题\"\n"
                "  \"message\": \"chore: 更新依赖库版本\"\n"
                "错误示例（禁止）：\n"
                "  \"message\": \"feat: add payment retry logic\"  ← 描述部分必须是中文\n"
                "所有 `reason` 字段的解释文字也必须是中文。\n\n"
            )
        if self.language == "en":
            return (
                "LANGUAGE REQUIREMENT: You MUST write ALL generated text "
                "in English only. Do NOT use any other language.\n"
            )
        return ""  # auto → no constraint

    def to_prompt_hint(self) -> str:
        """Return style hints to inject after the main system prompt.

        Language is handled separately via language_preamble (placed at top).
        """
        lines: list[str] = []

        # Language note omitted here — handled by language_preamble at prompt top

        # Commit style
        emoji_hint = "Include a relevant emoji prefix (e.g. ✨ feat:, 🐛 fix:)." if self.commit_emoji \
            else "Do NOT use emoji in commit messages."
        lines.append(emoji_hint)

        scope_hint = "Include a scope in parentheses when the module is clear (e.g. feat(payment): ...)." if self.commit_scope \
            else "Do NOT include a scope — use plain type prefix only (e.g. feat: ...)."
        lines.append(scope_hint)

        length_map = {
            "brief": "Keep commit messages very short (≤50 chars for the subject line).",
            "standard": "Keep commit messages concise (≤72 chars for the subject line).",
            "detailed": "Write descriptive commit messages; a short body explaining WHY is appreciated.",
        }
        lines.append(length_map[self.commit_length])

        # Ticket
        if self.ticket_format == "jira":
            prefix_hint = f" with prefix {self.ticket_pattern}" if self.ticket_pattern else ""
            lines.append(f"Append the JIRA ticket number{prefix_hint} at the end if found in the branch name (e.g. [PAY-234]).")
        elif self.ticket_format == "github":
            lines.append("Append the GitHub issue number at the end if found in the branch name (e.g. (#234)).")
        elif self.ticket_format == "auto":
            lines.append("If a ticket/issue number is detectable from the branch name, append it.")
        # none → don't mention tickets

        # Standup
        audience_hint = "The standup is for a TECHNICAL audience — implementation details and module names are fine." \
            if self.standup_audience == "technical" \
            else "The standup is for a NON-TECHNICAL audience (product/management) — focus on impact and outcomes, avoid jargon."
        lines.append(audience_hint)

        format_hint = "Format the standup as a bullet list." if self.standup_format == "bullets" \
            else "Format the standup as natural prose paragraphs."
        lines.append(format_hint)

        return "\n".join(f"- {l}" for l in lines)


# ── Persistence ───────────────────────────────────────────────────────────────

def load_preferences() -> UserPreferences:
    """Load saved preferences or return defaults."""
    if not GLOBAL_CONFIG_FILE.exists():
        return UserPreferences()
    try:
        data = yaml.safe_load(GLOBAL_CONFIG_FILE.read_text()) or {}
        prefs_data = data.get("preferences", {})
        return UserPreferences.model_validate(prefs_data) if prefs_data else UserPreferences()
    except Exception:
        return UserPreferences()


def save_preferences(prefs: UserPreferences) -> None:
    """Merge preferences into global config file."""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if GLOBAL_CONFIG_FILE.exists():
        try:
            data = yaml.safe_load(GLOBAL_CONFIG_FILE.read_text()) or {}
        except Exception:
            data = {}
    data["preferences"] = prefs.model_dump()
    GLOBAL_CONFIG_FILE.write_text(yaml.dump(data, allow_unicode=True))


def has_preferences() -> bool:
    """Return True if preferences have already been set."""
    if not GLOBAL_CONFIG_FILE.exists():
        return False
    try:
        data = yaml.safe_load(GLOBAL_CONFIG_FILE.read_text()) or {}
        return "preferences" in data
    except Exception:
        return False


# ── Onboarding questionnaire ──────────────────────────────────────────────────

def run_preferences_survey(skip_banner: bool = False) -> UserPreferences:
    """Interactive preference survey. Returns saved UserPreferences."""

    if not skip_banner:
        console.print()
        console.print(Panel(
            "[bold]让 gitsage 更了解你[/bold]\n\n"
            "几个简单的问题，帮助 gitsage 生成更符合你习惯的内容。\n"
            "之后可随时用 [bold cyan]gitsage preferences[/bold cyan] 修改。",
            title="[bold cyan]⚙️  个人偏好设置[/bold cyan]",
            expand=False,
        ))

    console.print()
    prefs = UserPreferences()

    # ── Q1: Language ──────────────────────────────────────────────────────────
    console.print("[bold]1 / 6  输出语言[/bold]")
    console.print("  gitsage 生成 commit message、站会内容时，优先用哪种语言？\n")
    console.print("  [cyan][1][/cyan] 中文")
    console.print("  [cyan][2][/cyan] English")
    console.print("  [cyan][3][/cyan] 自动（跟随仓库历史 commit 的语言）← 推荐\n")
    lang_choice = Prompt.ask("  选择", choices=["1", "2", "3"], default="3")
    prefs.language = {"1": "zh", "2": "en", "3": "auto"}[lang_choice]

    # ── Q2: Emoji ─────────────────────────────────────────────────────────────
    console.print()
    console.print("[bold]2 / 6  Commit message 风格[/bold]")
    console.print("  Commit message 里加 emoji 吗？\n")
    console.print("  [cyan][1][/cyan] 加，比如 [green]✨ feat(payment): 新增重试机制[/green]")
    console.print("  [cyan][2][/cyan] 不加，比如 [green]feat(payment): 新增重试机制[/green] ← 推荐\n")
    emoji_choice = Prompt.ask("  选择", choices=["1", "2"], default="2")
    prefs.commit_emoji = emoji_choice == "1"

    # ── Q3: Scope ─────────────────────────────────────────────────────────────
    console.print()
    console.print("[bold]3 / 6  是否带模块 scope[/bold]")
    console.print("  Commit type 后面带括号标注模块吗？\n")
    console.print("  [cyan][1][/cyan] 带，比如 [green]feat(payment): ...[/green] ← 推荐")
    console.print("  [cyan][2][/cyan] 不带，比如 [green]feat: ...[/green]\n")
    scope_choice = Prompt.ask("  选择", choices=["1", "2"], default="1")
    prefs.commit_scope = scope_choice == "1"

    # ── Q4: Commit length ─────────────────────────────────────────────────────
    console.print()
    console.print("[bold]4 / 6  Commit message 长度偏好[/bold]\n")
    console.print("  [cyan][1][/cyan] 简洁（主题行 ≤ 50 字符）")
    console.print("  [cyan][2][/cyan] 标准（主题行 ≤ 72 字符）← 推荐")
    console.print("  [cyan][3][/cyan] 详细（主题行 + 正文，解释 why）\n")
    length_choice = Prompt.ask("  选择", choices=["1", "2", "3"], default="2")
    prefs.commit_length = {"1": "brief", "2": "standard", "3": "detailed"}[length_choice]

    # ── Q5: Ticket format ─────────────────────────────────────────────────────
    console.print()
    console.print("[bold]5 / 6  Ticket / Issue 追踪格式[/bold]")
    console.print("  分支名里有 ticket 号时，自动加到 commit message 里吗？\n")
    console.print("  [cyan][1][/cyan] 自动识别（JIRA 格式 ABC-123 或 GitHub #123）← 推荐")
    console.print("  [cyan][2][/cyan] JIRA 格式（如 PAY-123，可指定前缀）")
    console.print("  [cyan][3][/cyan] GitHub Issues（#123）")
    console.print("  [cyan][4][/cyan] 不追踪\n")
    ticket_choice = Prompt.ask("  选择", choices=["1", "2", "3", "4"], default="1")
    prefs.ticket_format = {"1": "auto", "2": "jira", "3": "github", "4": "none"}[ticket_choice]

    if prefs.ticket_format == "jira":
        console.print("  [dim]你们的 JIRA project key 是什么？（如 PAY、PROJ，留空则自动检测）[/dim]")
        prefix = Prompt.ask("  JIRA prefix", default="")
        prefs.ticket_pattern = prefix.strip().upper()

    # ── Q6: Standup audience ──────────────────────────────────────────────────
    console.print()
    console.print("[bold]6 / 6  站会发言的对象[/bold]\n")
    console.print("  [cyan][1][/cyan] 技术团队（可以提模块名、实现细节）← 推荐")
    console.print("  [cyan][2][/cyan] 产品 / 管理层（只说影响和结论，不说技术细节）\n")
    audience_choice = Prompt.ask("  选择", choices=["1", "2"], default="1")
    prefs.standup_audience = "technical" if audience_choice == "1" else "nontechnical"

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    _show_preferences_summary(prefs)

    if Confirm.ask("\n保存这些偏好？", default=True):
        save_preferences(prefs)
        rprint(f"\n[green]✅ 偏好已保存[/green]  （修改：[cyan]gitsage preferences[/cyan]）")
    else:
        if Confirm.ask("重新回答？", default=True):
            return run_preferences_survey(skip_banner=True)

    return prefs


def _show_preferences_summary(prefs: UserPreferences) -> None:
    """Print a readable summary of the collected preferences."""
    from rich.table import Table

    lang_labels = {"zh": "中文", "en": "English", "auto": "自动跟随仓库"}
    length_labels = {"brief": "简洁 (≤50)", "standard": "标准 (≤72)", "detailed": "详细"}
    ticket_labels = {"auto": "自动识别", "jira": "JIRA", "github": "GitHub Issues", "none": "不追踪"}
    audience_labels = {"technical": "技术团队", "nontechnical": "产品/管理层"}
    format_labels = {"bullets": "Bullet 列表", "paragraph": "自然段落"}

    table = Table(title="[bold]偏好设置摘要[/bold]", show_header=False, box=None, padding=(0, 2))
    table.add_column("项目", style="dim")
    table.add_column("值", style="bold")

    table.add_row("输出语言", lang_labels.get(prefs.language, prefs.language))
    table.add_row("Emoji", "✅ 启用" if prefs.commit_emoji else "❌ 不用")
    table.add_row("Scope", "✅ 带（feat(module): ...）" if prefs.commit_scope else "❌ 不带")
    table.add_row("Commit 长度", length_labels.get(prefs.commit_length, ""))
    ticket_display = ticket_labels.get(prefs.ticket_format, "")
    if prefs.ticket_format == "jira" and prefs.ticket_pattern:
        ticket_display += f"（前缀: {prefs.ticket_pattern}）"
    table.add_row("Ticket 追踪", ticket_display)
    table.add_row("站会对象", audience_labels.get(prefs.standup_audience, ""))
    table.add_row("站会格式", format_labels.get(prefs.standup_format, ""))

    console.print(table)
