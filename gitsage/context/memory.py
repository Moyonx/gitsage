from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path.home() / ".gitsage" / "memory"
SUMMARIZE_EVERY = 20   # trigger LLM summarization every N raw observations

_RAW_SECTION_HEADER = "## Raw Observations"
_SUMMARY_SECTION_HEADER = "## Summary"


class MemoryManager:
    """Persistent per-repository memory stored as a Markdown file.

    Structure of the memory file::

        ## Summary
        <LLM-generated summary text>

        ## Raw Observations
        - [2024-01-15 09:32] commit: added auth module
        - [2024-01-15 10:05] standup: reported PR review work
    """

    def __init__(self, repo_name: str):
        self._repo_name = repo_name
        repo_hash = hashlib.md5(repo_name.encode()).hexdigest()[:12]
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_name)
        self._path = MEMORY_DIR / f"{safe_name}_{repo_hash}.md"
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self) -> str:
        """Return current memory content, empty string if file does not exist."""
        if not self._path.is_file():
            return ""
        return self._path.read_text(encoding="utf-8")

    def append_observation(self, task: str, observation: str) -> None:
        """Append a raw observation entry to the memory file.

        Creates the file if it does not exist. After appending, callers can
        check *should_summarize()* and trigger LLM summarization if needed.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{timestamp}] {task}: {observation}"

        content = self.read()

        if _RAW_SECTION_HEADER in content:
            # Append inside existing raw section
            content = content.rstrip() + "\n" + entry + "\n"
        else:
            # Create raw section
            if content:
                content = content.rstrip() + "\n\n"
            content += f"{_RAW_SECTION_HEADER}\n{entry}\n"

        self._path.write_text(content, encoding="utf-8")

    def _count_raw_observations(self) -> int:
        """Count the number of raw observation lines in the memory file."""
        content = self.read()
        if _RAW_SECTION_HEADER not in content:
            return 0
        raw_start = content.index(_RAW_SECTION_HEADER) + len(_RAW_SECTION_HEADER)
        raw_section = content[raw_start:]
        return sum(1 for line in raw_section.splitlines() if line.strip().startswith("- ["))

    def should_summarize(self) -> bool:
        """Return True when raw observation count has reached SUMMARIZE_EVERY."""
        return self._count_raw_observations() >= SUMMARIZE_EVERY

    def get_raw_observations(self) -> list[str]:
        """Return the list of raw observation strings (without the leading '- ')."""
        content = self.read()
        if _RAW_SECTION_HEADER not in content:
            return []
        raw_start = content.index(_RAW_SECTION_HEADER) + len(_RAW_SECTION_HEADER)
        raw_section = content[raw_start:]
        observations = []
        for line in raw_section.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                observations.append(stripped[2:])
            elif stripped.startswith("-") and len(stripped) > 1:
                observations.append(stripped[1:].strip())
        return observations

    def update_summary(self, llm_summary: str) -> None:
        """Replace the LLM summary section and clear all raw observations.

        Called after the LLM has produced a condensed summary of the raw
        observations. The raw observations are removed to keep the file size
        manageable.
        """
        content = self.read()

        # Remove existing summary section
        if _SUMMARY_SECTION_HEADER in content:
            summary_start = content.index(_SUMMARY_SECTION_HEADER)
            after_header = summary_start + len(_SUMMARY_SECTION_HEADER)
            next_section = re.search(r"\n## ", content[after_header:])
            if next_section:
                content = content[:summary_start] + content[after_header + next_section.start():]
            else:
                content = content[:summary_start]

        # Remove raw observations section entirely
        if _RAW_SECTION_HEADER in content:
            raw_start = content.index(_RAW_SECTION_HEADER)
            content = content[:raw_start].rstrip()

        # Rebuild: summary first, then empty raw section
        new_content = f"{_SUMMARY_SECTION_HEADER}\n{llm_summary.strip()}\n"
        if content.strip():
            new_content = content.strip() + "\n\n" + new_content

        self._path.write_text(new_content, encoding="utf-8")

    def clear(self) -> None:
        """Delete the memory file entirely."""
        if self._path.is_file():
            self._path.unlink()
