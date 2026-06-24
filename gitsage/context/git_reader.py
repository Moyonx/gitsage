from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import re

import git


@dataclass
class CommitInfo:
    sha: str
    short_sha: str
    message: str
    author: str
    date: datetime
    files_changed: list[str] = field(default_factory=list)


@dataclass
class GitState:
    repo_path: Path
    repo_name: str          # owner/repo or just folder name
    branch_name: str
    staged_diff: str        # full diff of staged changes
    staged_files: list[str]
    staged_summary: str     # short summary like "3 files changed, +45/-12"
    recent_commits: list[CommitInfo]   # last 10
    today_commits: list[CommitInfo]    # commits from today
    is_clean: bool          # no staged changes


class GitReader:
    """Read git repository state using GitPython."""

    def __init__(self, path: Path = None):
        self._path = path or Path.cwd()
        try:
            self._repo = git.Repo(self._path, search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            raise ValueError(f"Not a git repository: {self._path}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self, commit_limit: int = 10) -> GitState:
        """Return a full snapshot of current repository state."""
        staged_diff = self.get_staged_diff()
        staged_files = self.get_staged_files()
        staged_summary = self._build_staged_summary(staged_diff, staged_files)
        recent = self.get_recent_commits(commit_limit)
        today = self.get_today_commits()

        return GitState(
            repo_path=Path(self._repo.working_dir),
            repo_name=self.get_repo_name(),
            branch_name=self.get_branch_name(),
            staged_diff=staged_diff,
            staged_files=staged_files,
            staged_summary=staged_summary,
            recent_commits=recent,
            today_commits=today,
            is_clean=len(staged_files) == 0,
        )

    def get_staged_diff(self) -> str:
        """Return the full unified diff of staged (cached) changes."""
        try:
            # diff between HEAD and index (staged)
            if self._repo.head.is_valid():
                diff = self._repo.git.diff("--cached")
            else:
                # No commits yet — diff against empty tree
                diff = self._repo.git.diff("--cached", "--diff-filter=A")
        except git.GitCommandError:
            diff = ""
        return diff

    def get_branch_diff(self, base_branch: str = "main") -> str:
        """Return unified diff of all changes on the current branch vs base_branch.

        Uses three-dot diff (git diff base...HEAD) which compares from the
        common ancestor, so it only shows changes made on this branch, not
        unrelated commits on base.

        Falls back to staged diff if branch comparison fails.
        """
        try:
            # Three-dot: shows only what this branch added/changed
            diff = self._repo.git.diff(f"{base_branch}...HEAD")
            if diff.strip():
                return diff
        except git.GitCommandError:
            pass
        # Fallback: try two-dot
        try:
            diff = self._repo.git.diff(f"{base_branch}..HEAD")
            if diff.strip():
                return diff
        except git.GitCommandError:
            pass
        # Final fallback: staged diff
        return self.get_staged_diff()

    def get_staged_files(self) -> list[str]:
        """Return list of file paths that are staged for commit."""
        try:
            if self._repo.head.is_valid():
                diff_index = self._repo.index.diff("HEAD")
            else:
                # No commits yet — everything in the index is staged
                diff_index = self._repo.index.diff(None)

            staged = [d.a_path for d in diff_index]

            # Also capture new untracked files that were git-added
            if self._repo.head.is_valid():
                # new files added to index not yet in HEAD
                staged_new = [
                    entry.path
                    for entry in self._repo.index.entries.values()
                    if entry.path not in staged
                ]
                # filter to only truly new (not in HEAD)
                try:
                    head_tree = self._repo.head.commit.tree
                    head_paths = {blob.path for blob in head_tree.traverse() if hasattr(blob, "path")}
                    staged += [p for p in staged_new if p not in head_paths]
                except Exception:
                    pass

            return sorted(set(staged))
        except Exception:
            return []

    def get_recent_commits(self, limit: int = 10) -> list[CommitInfo]:
        """Return up to *limit* most recent commits."""
        try:
            commits = list(self._repo.iter_commits(max_count=limit))
            return [self._commit_to_info(c) for c in commits]
        except git.GitCommandError:
            return []
        except ValueError:
            # No commits in repo
            return []

    def get_today_commits(self) -> list[CommitInfo]:
        """Return commits authored today (local date)."""
        try:
            today = datetime.now().date()
            result = []
            for commit in self._repo.iter_commits():
                commit_date = datetime.fromtimestamp(commit.authored_date).date()
                if commit_date == today:
                    result.append(self._commit_to_info(commit))
                elif commit_date < today:
                    # Commits are in reverse-chronological order; stop early
                    break
            return result
        except (git.GitCommandError, ValueError):
            return []

    def get_branch_name(self) -> str:
        """Return current branch name, or "(detached HEAD)" if detached."""
        try:
            return self._repo.active_branch.name
        except TypeError:
            # Detached HEAD
            try:
                return f"(detached:{self._repo.head.commit.hexsha[:8]})"
            except Exception:
                return "(detached HEAD)"

    def get_repo_name(self) -> str:
        """Return owner/repo from remote URL, or folder name as fallback."""
        try:
            remote = self._repo.remotes[0]
            url = remote.url
            # Strip .git suffix and extract last two path components
            url = url.rstrip("/")
            if url.endswith(".git"):
                url = url[:-4]
            # SSH: git@github.com:owner/repo  or  HTTPS: https://github.com/owner/repo
            if ":" in url and "@" in url:
                # SSH form
                path_part = url.split(":", 1)[1]
            else:
                # HTTPS form — take last two segments
                parts = url.split("/")
                path_part = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
            return path_part
        except (IndexError, AttributeError, Exception):
            # Fall back to working directory folder name
            return Path(self._repo.working_dir).name

    def analyze_commit_patterns(self, limit: int = 50) -> dict:
        """Analyse recent commits and return a dict of detected style patterns.

        Returns a dict with keys:
            language        "zh" | "en" | "mixed"
            uses_emoji      bool
            uses_type       bool  (feat/fix/chore prefix)
            uses_scope      bool  (feat(scope): ...)
            avg_length      int   (chars, subject line)
            top_scopes      list[str]  (most frequent scopes)
            top_types       list[str]  (most frequent types)
            sample_msgs     list[str]  (3 representative messages)
        """
        import unicodedata

        try:
            raw = list(self._repo.iter_commits("HEAD", max_count=limit))
        except Exception:
            return {}

        messages = [c.message.strip().splitlines()[0] for c in raw if c.message.strip()]
        if not messages:
            return {}

        # Emoji detection: any char in Emoji category
        def has_emoji(s: str) -> bool:
            return any(unicodedata.category(ch) in ("So", "Sm") or ord(ch) > 0x1F000 for ch in s)

        # CJK ratio
        def cjk_ratio(s: str) -> float:
            cjk = sum(1 for ch in s if "一" <= ch <= "鿿")
            return cjk / max(len(s), 1)

        # Conventional commits pattern
        _TYPE_RE = re.compile(r"^(feat|fix|chore|refactor|docs|test|style|perf|ci|build|revert)(\(.+?\))?!?:\s", re.IGNORECASE)

        emoji_count = sum(1 for m in messages if has_emoji(m))
        type_count = sum(1 for m in messages if _TYPE_RE.match(m))
        scope_matches = [_TYPE_RE.match(m) for m in messages]
        scope_count = sum(1 for m in scope_matches if m and m.group(2))

        # Average length
        avg_len = int(sum(len(m) for m in messages) / len(messages))

        # Top scopes
        from collections import Counter
        scopes = [m.group(2).strip("()") for m in scope_matches if m and m.group(2)]
        top_scopes = [s for s, _ in Counter(scopes).most_common(5)]

        # Top types
        types = [_TYPE_RE.match(m).group(1).lower() for m in messages if _TYPE_RE.match(m)]
        top_types = [t for t, _ in Counter(types).most_common(5)]

        # Language
        cjk_ratios = [cjk_ratio(m) for m in messages]
        avg_cjk = sum(cjk_ratios) / len(cjk_ratios)
        if avg_cjk > 0.3:
            language = "zh"
        elif avg_cjk > 0.1:
            language = "mixed"
        else:
            language = "en"

        # Sample messages: pick 3 representative ones
        sample_msgs = messages[:3]

        return {
            "language": language,
            "uses_emoji": emoji_count / len(messages) > 0.3,
            "uses_type": type_count / len(messages) > 0.5,
            "uses_scope": scope_count / len(messages) > 0.3,
            "avg_length": avg_len,
            "top_scopes": top_scopes,
            "top_types": top_types,
            "sample_msgs": sample_msgs,
            "total_analyzed": len(messages),
        }

    def get_file_blame(self, filepath: str) -> list[dict]:
        """Return blame information for *filepath*.

        Each entry is a dict with keys: sha, author, date, line, content.
        """
        try:
            blame = self._repo.blame("HEAD", filepath)
            result = []
            line_num = 1
            for commit, lines in blame:
                for line in lines:
                    content = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
                    result.append({
                        "sha": commit.hexsha,
                        "author": str(commit.author),
                        "date": datetime.fromtimestamp(commit.authored_date),
                        "line": line_num,
                        "content": content,
                    })
                    line_num += 1
            return result
        except (git.GitCommandError, Exception):
            return []

    def get_file_log(self, filepath: str, limit: int = 20) -> list[CommitInfo]:
        """Return commit history for a specific file."""
        try:
            commits = list(self._repo.iter_commits(paths=filepath, max_count=limit))
            return [self._commit_to_info(c) for c in commits]
        except (git.GitCommandError, ValueError):
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _commit_to_info(self, commit: git.Commit) -> CommitInfo:
        """Convert a GitPython Commit object to CommitInfo."""
        try:
            files_changed = list(commit.stats.files.keys())
        except Exception:
            files_changed = []

        return CommitInfo(
            sha=commit.hexsha,
            short_sha=commit.hexsha[:8],
            message=commit.message.strip(),
            author=str(commit.author),
            date=datetime.fromtimestamp(commit.authored_date),
            files_changed=files_changed,
        )

    def _build_staged_summary(self, diff: str, staged_files: list[str]) -> str:
        """Build a short human-readable summary of staged changes."""
        if not staged_files:
            return "nothing staged"

        file_count = len(staged_files)
        additions = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))

        file_word = "file" if file_count == 1 else "files"
        return f"{file_count} {file_word} changed, +{additions}/-{deletions}"
