"""Git blame and commit context fetcher for gitsage explain."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import git


@dataclass
class BlameEntry:
    sha: str
    short_sha: str
    author: str
    date: datetime
    line_number: int
    content: str


@dataclass
class CommitDetail:
    """A commit with optional PR/Issue context."""
    sha: str
    short_sha: str
    message: str
    author: str
    date: datetime
    # GitHub context (only when token available)
    pr_number: Optional[int] = None
    pr_title: Optional[str] = None
    pr_body: Optional[str] = None
    issue_numbers: list[int] = field(default_factory=list)
    issue_titles: list[str] = field(default_factory=list)
    issue_bodies: list[str] = field(default_factory=list)


@dataclass
class BlameContext:
    """Complete blame context for a file."""
    file_path: str
    file_content: str
    language: str  # python, java, go, etc. (detected from extension)
    commits: list[CommitDetail]  # unique commits, most recent first
    local_only: bool  # True if no GitHub enrichment


_EXTENSION_MAP = {
    ".py": "Python", ".java": "Java", ".go": "Go",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".rs": "Rust", ".kt": "Kotlin", ".swift": "Swift",
    ".cpp": "C++", ".c": "C", ".cs": "C#",
    ".rb": "Ruby", ".php": "PHP", ".scala": "Scala",
}

_PR_PATTERN = re.compile(r'\(#(\d+)\)|Merge pull request #(\d+)|PR[- ]#?(\d+)', re.IGNORECASE)
_ISSUE_PATTERN = re.compile(r'(?:closes?|fixes?|resolves?)\s+#(\d+)', re.IGNORECASE)


def _detect_language(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    return _EXTENSION_MAP.get(ext, "Unknown")


def _extract_pr_number(message: str) -> Optional[int]:
    m = _PR_PATTERN.search(message)
    if m:
        return int(next(g for g in m.groups() if g is not None))
    return None


class BlameContextBuilder:
    """Builds BlameContext for a file using local git history + optional GitHub."""

    MAX_COMMITS = 10  # cap to keep context manageable

    def __init__(self, repo_path: Path = None, github_token: str = "") -> None:
        self._root = repo_path or Path.cwd()
        self._repo = git.Repo(self._root, search_parent_directories=True)
        self._repo_root = Path(self._repo.working_tree_dir)
        self._github_token = github_token

    def build(self, file_path: str) -> BlameContext:
        """Build complete context for the given file."""
        abs_path = (self._root / file_path).resolve()
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found: {abs_path}")

        # Make path relative to repo root for git operations
        try:
            rel_path = abs_path.relative_to(self._repo_root)
        except ValueError:
            rel_path = Path(file_path)

        file_content = abs_path.read_text(encoding="utf-8", errors="replace")
        language = _detect_language(str(rel_path))

        # Get blame
        blame_entries = self._get_blame(str(rel_path))

        # Unique commits (most recent first, capped)
        seen: dict[str, CommitDetail] = {}
        for entry in blame_entries:
            if entry.sha not in seen:
                seen[entry.sha] = self._build_commit_detail(entry)

        commits = list(seen.values())[:self.MAX_COMMITS]

        # Enrich with GitHub context if token available
        local_only = True
        if self._github_token:
            try:
                self._enrich_with_github(commits)
                local_only = False
            except Exception:
                pass  # Gracefully fall back to local-only

        return BlameContext(
            file_path=str(rel_path),
            file_content=file_content[:8000],  # cap file content
            language=language,
            commits=commits,
            local_only=local_only,
        )

    def _get_blame(self, rel_path: str) -> list[BlameEntry]:
        entries: list[BlameEntry] = []
        try:
            blame = self._repo.blame("HEAD", rel_path)
        except git.GitCommandError:
            return entries

        line_num = 1
        for commit, lines in blame:
            for line in lines:
                content = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
                entries.append(BlameEntry(
                    sha=commit.hexsha,
                    short_sha=commit.hexsha[:7],
                    author=commit.author.name,
                    date=datetime.fromtimestamp(commit.authored_date),
                    line_number=line_num,
                    content=content.rstrip(),
                ))
                line_num += 1
        return entries

    def _build_commit_detail(self, entry: BlameEntry) -> CommitDetail:
        try:
            commit = self._repo.commit(entry.sha)
            message = commit.message.strip()
            pr_number = _extract_pr_number(message)
            issue_numbers = [int(m) for m in _ISSUE_PATTERN.findall(message)]
            return CommitDetail(
                sha=entry.sha,
                short_sha=entry.short_sha,
                message=message,
                author=entry.author,
                date=entry.date,
                pr_number=pr_number,
                issue_numbers=issue_numbers,
            )
        except Exception:
            return CommitDetail(
                sha=entry.sha, short_sha=entry.short_sha,
                message="(could not read)", author=entry.author,
                date=entry.date,
            )

    def _enrich_with_github(self, commits: list[CommitDetail]) -> None:
        """Fetch PR and Issue details from GitHub for commits that have PR numbers."""
        from github import Github, GithubException
        import re as _re

        # Detect repo name from remote URL
        remote_url = self._repo.remotes[0].url if self._repo.remotes else ""
        match = _re.search(r'github\.com[:/](.+?)(?:\.git)?$', remote_url)
        if not match:
            return

        gh = Github(self._github_token)
        repo = gh.get_repo(match.group(1))

        for commit in commits:
            if commit.pr_number:
                try:
                    pr = repo.get_pull(commit.pr_number)
                    commit.pr_title = pr.title
                    commit.pr_body = (pr.body or "")[:800]
                    # Get linked issues from PR body
                    for inum in _ISSUE_PATTERN.findall(commit.pr_body):
                        issue_num = int(inum)
                        if issue_num not in commit.issue_numbers:
                            commit.issue_numbers.append(issue_num)
                except GithubException:
                    pass

            # Fetch issue titles/bodies
            for inum in commit.issue_numbers[:3]:  # cap at 3 per commit
                try:
                    issue = repo.get_issue(inum)
                    commit.issue_titles.append(issue.title)
                    commit.issue_bodies.append((issue.body or "")[:500])
                except GithubException:
                    pass
