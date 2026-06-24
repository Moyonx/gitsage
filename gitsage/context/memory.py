from __future__ import annotations

import hashlib
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agent.llm import BaseLLMClient

logger = logging.getLogger(__name__)

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

    def summarize_with_llm(self, llm_client: "BaseLLMClient") -> None:
        """Call the LLM to condense raw observations into a structured summary.

        Replaces the Summary section and clears raw observations.
        Silently swallows errors so the caller is never blocked.
        """
        observations = self.get_raw_observations()
        if not observations:
            return

        from ..agent.models import StandupOutput  # reuse simple model for summary

        obs_text = "\n".join(f"- {o}" for o in observations)
        prompt = (
            f"You are summarising developer activity for repository '{self._repo_name}'.\n\n"
            f"Raw observations (recent commits and actions):\n{obs_text}\n\n"
            "Write a concise structured summary covering:\n"
            "1. The developer's preferred commit style (emoji, language, format)\n"
            "2. Which modules they work on most\n"
            "3. Any recurring patterns or preferences\n"
            "4. Current work context (what they seem to be working on now)\n\n"
            "Keep it under 200 words. This summary will be used to personalise "
            "future AI-generated commit messages and standups."
        )

        try:
            # We use StandupOutput as a simple container; only 'content' is used
            result = llm_client.complete(
                system="You summarise developer activity concisely. Output JSON only.",
                user=prompt,
                output_model=StandupOutput,
            )
            self.update_summary(result.content)
            logger.debug("Memory summarised for %s", self._repo_name)
        except Exception as e:
            logger.debug("Memory summarisation failed (non-fatal): %s", e)

    def record_commit(
        self,
        message: str,
        category: str = "",
        branch: str = "",
        llm_client: "BaseLLMClient | None" = None,
    ) -> None:
        """Record a successful commit and optionally trigger background summarisation.

        Designed to be called from a background thread so it never blocks
        the main CLI flow.
        """
        scope_info = f" branch={branch}" if branch else ""
        cat_info = f" type={category}" if category else ""
        observation = f'"{message}"{cat_info}{scope_info}'
        self.append_observation("commit", observation)

        if llm_client and self.should_summarize():
            self.summarize_with_llm(llm_client)

    def clear(self) -> None:
        """Delete the memory file entirely."""
        if self._path.is_file():
            self._path.unlink()


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def update_memory_async(
    repo_name: str,
    message: str,
    category: str = "",
    branch: str = "",
    llm_client: "BaseLLMClient | None" = None,
) -> None:
    """Fire-and-forget: record a commit in memory on a daemon thread.

    Errors are swallowed — memory is best-effort and must never block the CLI.
    """
    def _work() -> None:
        try:
            mem = MemoryManager(repo_name)
            mem.record_commit(
                message=message,
                category=category,
                branch=branch,
                llm_client=llm_client,
            )
        except Exception as e:
            logger.debug("Memory update failed (non-fatal): %s", e)

    t = threading.Thread(target=_work, daemon=True, name="gitsage-memory")
    t.start()
