from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Callable

@dataclass
class Rule:
    name: str
    check: Callable[[str], bool]  # returns True if OK
    on_fail: str  # "retry" | "filter" | "warn"
    message: str  # description of the violation

@dataclass
class GateResult:
    passed: bool
    violations: list[Rule]
    message: str

class QualityGate:
    """Validates LLM output against configurable rules."""

    def __init__(self, rules: list[Rule] = None):
        self._rules = rules or []

    def check(self, text: str) -> GateResult:
        violations = [r for r in self._rules if not r.check(text)]
        return GateResult(
            passed=len(violations) == 0,
            violations=violations,
            message="; ".join(v.message for v in violations) if violations else "OK"
        )

    @classmethod
    def for_commit(cls, max_chars: int = 72, language: str = "en") -> "QualityGate":
        """Standard commit message quality gate."""
        rules = [
            Rule("max_length", lambda t: len(t) <= max_chars, "retry",
                 f"Too long ({max_chars} char limit)"),
            Rule("not_empty", lambda t: bool(t.strip()), "retry", "Empty message"),
            Rule("no_file_paths", lambda t: not re.search(r'\b\w+\.\w{2,4}\b', t)
                 or not re.search(r'[/\\]', t), "filter", "Contains file paths"),
        ]
        return cls(rules)

    @classmethod
    def for_standup(cls) -> "QualityGate":
        rules = [
            Rule("not_empty", lambda t: len(t.strip()) > 20, "retry", "Too short"),
        ]
        return cls(rules)
