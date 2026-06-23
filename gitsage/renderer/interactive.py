from __future__ import annotations
import subprocess
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import print as rprint
from ..agent.models import CommitCandidate, CommitOutput

console = Console()

CONFIDENCE_COLORS = {"high": "green", "medium": "yellow", "low": "red"}
CONFIDENCE_ICONS = {"high": "OK", "medium": "!", "low": "?"}

def show_commit_candidates(output: CommitOutput) -> str | None:
    """Show commit candidates interactively. Returns chosen message or None."""
    console.print()

    if output.warning:
        rprint(f"[yellow]  {output.warning}[/yellow]")
        console.print()

    for i, c in enumerate(output.candidates, 1):
        icon = CONFIDENCE_ICONS.get(c.confidence, "*")
        color = CONFIDENCE_COLORS.get(c.confidence, "white")
        prefix = f"[bold][{i}][/bold]"

        if i == 1:
            console.print(f"{prefix} {icon} [bold {color}]{c.message}[/bold {color}]")
        else:
            console.print(f"{prefix}    [dim]{c.message}[/dim]")

        console.print(f"     [dim]{c.reason}[/dim]")

    console.print()

    while True:
        choice = Prompt.ask(
            "Enter to accept [1], number to select, [bold]e[/bold] to edit, [bold]q[/bold] to quit",
            default="1"
        )

        if choice.lower() == "q":
            return None

        if choice.lower() == "e":
            chosen = output.candidates[0].message
            edited = _edit_in_editor(chosen)
            return edited

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(output.candidates):
                return output.candidates[idx].message
        except ValueError:
            pass

        rprint("[red]Invalid choice, please try again[/red]")

def execute_git_commit(message: str) -> bool:
    """Execute git commit with the given message. Returns True if successful."""
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            rprint(f"\n[green]{result.stdout.strip()}[/green]")
            return True
        else:
            rprint(f"\n[red]git commit failed:[/red] {result.stderr.strip()}")
            return False
    except Exception as e:
        rprint(f"\n[red]Error:[/red] {e}")
        return False

def _edit_in_editor(text: str) -> str:
    """Open text in $EDITOR for editing."""
    import os
    import tempfile
    editor = os.environ.get("EDITOR", "nano")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        fname = f.name
    subprocess.run([editor, fname])
    with open(fname) as f:
        result = f.read().strip()
    os.unlink(fname)
    return result

def show_standup(content: str) -> None:
    console.print(Panel(content, title="[bold cyan]Standup[/bold cyan]", expand=False))

def show_pr(title: str, description: str) -> None:
    body = f"**{title}**\n\n{description}"
    console.print(Panel(body, title="[bold cyan]PR Description[/bold cyan]", expand=False))
