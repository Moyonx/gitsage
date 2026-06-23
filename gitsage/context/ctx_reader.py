from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CTXContent:
    raw: str                    # full file content
    project_background: str     # extracted from ## 项目背景 or ## Project Background
    commit_rules: str           # extracted from ## Commit 规范 section
    standup_format: str         # extracted from ## Standup 格式 section
    pr_rules: str               # extracted from ## PR section if any
    always_rules: list[str] = field(default_factory=list)   # from always: yaml list
    never_rules: list[str] = field(default_factory=list)    # from never: yaml list
    language: str = "en"        # "zh" or "en"
    is_empty: bool = False      # True if no CTX.md found


_EMPTY = CTXContent(
    raw="",
    project_background="",
    commit_rules="",
    standup_format="",
    pr_rules="",
    always_rules=[],
    never_rules=[],
    language="en",
    is_empty=True,
)


class CTXReader:
    """Locate and parse CTX.md (and optional CTX.local.md) files."""

    def __init__(self, start_path: Path = None):
        self._start = start_path or Path.cwd()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self) -> CTXContent:
        """Find CTX.md walking up the directory tree, parse it.

        If CTX.local.md exists alongside CTX.md its content is appended
        (local file takes precedence for duplicate sections by appearing last).
        """
        ctx_path = self.find_ctx_file()
        if ctx_path is None:
            return _EMPTY

        content = ctx_path.read_text(encoding="utf-8", errors="replace")

        # Merge CTX.local.md if present
        local_path = ctx_path.parent / "CTX.local.md"
        if local_path.is_file():
            local_content = local_path.read_text(encoding="utf-8", errors="replace")
            content = content + "\n\n" + local_content

        return self._parse(content)

    def find_ctx_file(self) -> Path | None:
        """Walk up from *self._start* looking for CTX.md."""
        current = self._start.resolve()
        while True:
            candidate = current / "CTX.md"
            if candidate.is_file():
                return candidate
            parent = current.parent
            if parent == current:
                return None
            current = parent

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse(self, content: str) -> CTXContent:
        """Parse raw CTX.md text into a CTXContent dataclass."""
        language = self._detect_language(content)

        project_background = self._extract_section(
            content,
            ["项目背景", "Project Background", "Background", "项目简介"],
        )
        commit_rules = self._extract_section(
            content,
            ["Commit 规范", "Commit规范", "Commit Rules", "Commit"],
        )
        standup_format = self._extract_section(
            content,
            ["Standup 格式", "Standup格式", "Standup Format", "Standup", "Daily Standup"],
        )
        pr_rules = self._extract_section(
            content,
            ["PR 规范", "PR规范", "PR Rules", "PR", "Pull Request"],
        )

        always_rules = self._parse_rules(content, "always")
        never_rules = self._parse_rules(content, "never")

        return CTXContent(
            raw=content,
            project_background=project_background,
            commit_rules=commit_rules,
            standup_format=standup_format,
            pr_rules=pr_rules,
            always_rules=always_rules,
            never_rules=never_rules,
            language=language,
            is_empty=False,
        )

    def _detect_language(self, content: str) -> str:
        """Return 'zh' if more than 30% of chars are CJK, else 'en'."""
        if not content:
            return "en"
        cjk_count = sum(
            1 for ch in content
            if "一" <= ch <= "鿿"
            or "㐀" <= ch <= "䶿"
        )
        ratio = cjk_count / len(content)
        return "zh" if ratio > 0.30 else "en"

    def _extract_section(self, content: str, headers: list[str]) -> str:
        """Extract the body of the first matching markdown section.

        Tries each header in *headers* in order. Stops at the next same-level
        or higher-level heading.
        """
        for header in headers:
            pattern = re.compile(
                r"^(#{1,4})\s*" + re.escape(header) + r"\s*$",
                re.MULTILINE | re.IGNORECASE,
            )
            match = pattern.search(content)
            if match:
                level = len(match.group(1))
                start = match.end()
                # Find the next heading of same or higher level
                next_heading = re.compile(
                    r"^#{1," + str(level) + r"}\s",
                    re.MULTILINE,
                )
                end_match = next_heading.search(content, start)
                end = end_match.start() if end_match else len(content)
                return content[start:end].strip()
        return ""

    def _parse_rules(self, content: str, keyword: str) -> list[str]:
        """Parse a YAML-ish list under *keyword*: in the content.

        Handles:
          always:
            - rule one
            - rule two
        """
        pattern = re.compile(
            r"^[ \t]*" + re.escape(keyword) + r"[ \t]*:[ \t]*$",
            re.MULTILINE | re.IGNORECASE,
        )
        match = pattern.search(content)
        if not match:
            return []

        lines = content[match.end():].splitlines()
        rules: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("- ") or stripped.startswith("* "):
                rules.append(stripped[2:].strip())
            elif stripped.startswith("-") and len(stripped) > 1:
                rules.append(stripped[1:].strip())
            else:
                # Stop at next non-list content
                if stripped.startswith("#") or (rules and not stripped.startswith(" ")):
                    break
        return rules
