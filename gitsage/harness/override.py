from __future__ import annotations
import re
from ..config import CTXRules

class DeterministicOverride:
    """Applies deterministic transformations to LLM output."""

    def __init__(self, rules: CTXRules, branch_name: str = ""):
        self._rules = rules
        self._branch_name = branch_name

    def apply_to_commit(self, message: str) -> str:
        """Apply all deterministic rules to a commit message."""
        message = self._inject_ticket(message)
        message = self._filter_forbidden(message)
        return message.strip()

    def _inject_ticket(self, message: str) -> str:
        """Extract ticket number from branch and inject if missing."""
        # Common patterns: PAY-234, JIRA-123, feature/PAY-234-description
        ticket_pattern = re.compile(r'([A-Z]{2,10}-\d+)', re.IGNORECASE)
        branch_match = ticket_pattern.search(self._branch_name)
        if not branch_match:
            return message
        ticket = branch_match.group(1).upper()
        # Already in message?
        if ticket in message.upper():
            return message
        # Check if "always inject_ticket" in rules
        inject = any("ticket" in rule.lower() or "jira" in rule.lower()
                     for rule in self._rules.always)
        if inject:
            return f"{message} [{ticket}]"
        return message

    def _filter_forbidden(self, message: str) -> str:
        """Remove forbidden patterns from output."""
        result = message
        for rule in self._rules.never:
            if "file" in rule.lower() and "path" in rule.lower():
                # Remove file paths like src/payment.py
                result = re.sub(r'\b[\w/\\]+\.\w{2,4}\b', '', result)
        return re.sub(r'\s+', ' ', result).strip()

    def check_never_rules(self, text: str) -> list[str]:
        """Return list of violated never-rules."""
        violations = []
        for rule in self._rules.never:
            # Simple heuristic check
            keywords = rule.lower().split()
            if any(kw in text.lower() for kw in keywords if len(kw) > 4):
                violations.append(rule)
        return violations
