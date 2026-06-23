from __future__ import annotations
import os
import subprocess
from enum import Enum
from pathlib import Path

class HookEvent(str, Enum):
    PRE_COMMIT = "pre-commit"
    POST_COMMIT = "post-commit"
    PRE_STANDUP = "pre-standup"
    POST_STANDUP = "post-standup"
    PRE_EXPLAIN = "pre-explain"
    POST_EXPLAIN = "post-explain"
    SESSION_START = "session-start"

class HookResult:
    def __init__(self, ran: bool, success: bool, output: str = "", error: str = ""):
        self.ran = ran
        self.success = success
        self.output = output
        self.error = error

class HookRunner:
    """Runs user-defined shell scripts at lifecycle events."""

    def __init__(self, repo_path: Path = None):
        self._hooks_dir = (repo_path or Path.cwd()) / ".gitsage" / "hooks"

    def run(self, event: HookEvent, env: dict = None) -> HookResult:
        """Run hook for the given event. Returns HookResult."""
        hook_path = self._hooks_dir / f"{event.value}.sh"
        if not hook_path.exists():
            return HookResult(ran=False, success=True)

        try:
            result = subprocess.run(
                ["bash", str(hook_path)],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, **(env or {})},
            )
            return HookResult(
                ran=True,
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
            )
        except subprocess.TimeoutExpired:
            return HookResult(ran=True, success=False, error="Hook timed out after 30s")
        except Exception as e:
            return HookResult(ran=True, success=False, error=str(e))
