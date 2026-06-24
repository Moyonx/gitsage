# Changelog

All notable changes to gitsage are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.0] — 2026-06-24

### Added

**MCP generation tools**
- `generate_commit_message` — AI-generates commit candidates for staged changes via MCP. Runs the complete gitsage commit pipeline (CTX.md rules, memory, quality gate, deterministic override, style preferences) and returns ranked candidates with confidence scores and reasons. Any MCP-compatible client (Claude Code, Cursor, etc.) can now trigger gitsage generation directly.
- `generate_standup` — AI-generates a standup report from today's commits via MCP. Respects CTX.md, memory and style preferences. Returns structured content with commit count and date.

**Skill management**
- `gitsage skill show <name>` — displays full SKILL.md content with Markdown syntax highlighting.
- `gitsage skill add [name]` — interactive wizard that creates a correctly-formed SKILL.md (frontmatter + structured body template) in project or global scope.
- `gitsage skill edit <name>` — opens a skill directly in `$EDITOR`.

**`config init` interactive review loop**
- After AI draft generation, users can apply natural-language modifications in a loop (e.g. "把站会格式改成英文", "加一条规则：禁止用英文") before saving. Modifications call a dedicated LLM pass and the updated content is shown immediately.
- Mixed-language repo detection now prompts for explicit language choice (zh/en) before generation.
- Multi-round pre-generation adjustment: each line adds an instruction; empty line proceeds to generate.

### Fixed

- `config init` review loop: `[y/回车]`, `[e]`, `[q]` shortcut labels were eaten by Rich's markup parser — escaped with `\[`.
- `config init` input prompts: Chinese text in `input()` prompt caused readline to miscount cursor width, making backspace leave residual characters. Replaced with `console.input()` throughout.
- CTX modify prompt / `StandupOutput` mismatch: system prompt said "output CTX.md only" while the code required JSON — the model returned empty content. Prompt updated to specify `{"content": "...", "items": []}` format.
- Language preamble injected at top of system prompt (not appended) for stronger model compliance.

### Changed

- MCP server description updated to reflect new generation capabilities.
- Project URLs in `pyproject.toml` corrected to `Moyonx/gitsage`.

---

## [0.1.0] — 2026-06-23

### Added

- **`gitsage commit`** — interactive commit message generation with 2–3 ranked candidates. Modes: `interactive` (default), `print`, `execute`, `hook` (for `prepare-commit-msg`). `--estimate` flag previews token cost.
- **`gitsage standup`** — standup report from today's commits. `--print` for pipe-friendly plain text output.
- **`gitsage pr`** — PR title and description for the current branch vs a base branch.
- **`gitsage explain <file>`** — code archaeology: traces why code exists using git blame, commit history, and optional GitHub PR/Issue enrichment. Iterative agent loop with tool calls.
- **`gitsage catchup`** — recent changes summary over a configurable time window.
- **`gitsage config init`** — analyses git history and AI-generates a `CTX.md` project context file.
- **`gitsage config show / set`** — view and modify configuration.
- **`gitsage setup`** — interactive LLM provider wizard (Anthropic, OpenAI, DeepSeek, Ollama).
- **`gitsage preferences`** — user preference survey: output language, emoji, scope, commit length, ticket format, standup audience.
- **`gitsage model list / set / test`** — model management and connection testing.
- **`gitsage memory show / clear`** — per-repo memory that summarises commit history and learned style.
- **`gitsage skill list`** — list available skills from project and global directories.
- **`gitsage install-hooks`** — installs `prepare-commit-msg` git hook for automatic suggestion on every `git commit`.
- **`gitsage install-completion`** — shell tab completion for bash/zsh/fish.
- **`gitsage doctor`** — environment and configuration health check.
- **MCP Server** (`gitsage mcp serve`) — exposes git state as MCP tools: `get_staged_diff`, `get_recent_commits`, `get_git_status`, `get_branch_info`, `get_file_history`.
- **`gitsage mcp install / status`** — register with Claude Desktop, Cursor, or any MCP client.
- **Harness layer** — `QualityGate` enforces commit message rules (length, language, verb-start); `DeterministicOverride` injects ticket numbers and strips forbidden content regardless of LLM output.
- **CTX.md** context system — project-level conventions file; parsed for commit rules, always/never rules, and language.
- **Memory system** — append-on-commit, LLM-summarised every 20 observations, per-repo Markdown file.
- **Skills system** — SKILL.md files in `.gitsage/skills/<name>/` inject domain-specific reasoning into prompts.
- **Graceful degradation** — rate limit handling, LLM unavailability fallback with diff summary, GitHub-token-less local mode for `explain`.

[0.2.0]: https://github.com/Moyonx/gitsage/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Moyonx/gitsage/releases/tag/v0.1.0
