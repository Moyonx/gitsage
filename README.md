# gitsage

> **Git-native AI developer workflow assistant.**
> Understands your code changes, learns your style, and helps you express your work — commit messages, standups, PR descriptions, and code archaeology.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-136%20passing-brightgreen.svg)](#)

---

## Why gitsage?

You already know what you changed. Expressing it clearly is the tedious part.

gitsage reads your **local git state** — staged diffs, blame history, recent commits — and uses AI to turn that context into clear, project-aware output. It learns your style over time and follows your team's conventions automatically.

```
# Before: staring at the diff wondering what to write
$ git add src/payment/retry.py

# After: gitsage does the thinking
$ gitsage commit

[1] ✅ feat(payment): add exponential backoff retry for failed payments [PAY-234]
       Retries up to 3 times with 1s/2s/4s intervals. Addresses the duplicate
       charge issue reported in high-traffic scenarios.

[2]    feat: add payment retry logic with backoff strategy
[3]    fix(payment): handle transient payment gateway failures

Enter to accept [1], number to select, e to edit, q to quit:
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Commit messages** | Generates 2–3 candidates ranked by confidence. Picks up ticket numbers from branch names automatically. |
| **Daily standups** | Reads today's commits, understands what you actually did, formats for your audience (tech team or management). |
| **PR descriptions** | Full PR body from branch diff — background, changes, testing notes. |
| **Code archaeology** | `gitsage explain` traces code through git history to answer *why* something was written this way. |
| **Learns your style** | Observes your commits over time, summarizes preferences to `~/.gitsage/memory/`. Outputs get better with use. |
| **Project conventions** | Drop a `CTX.md` in your repo root — commit format, audience, rules. The whole team shares it. |
| **Quality gates** | Every output passes length, format, and language checks before you see it. Rules from `CTX.md` are enforced deterministically, not by hoping the LLM cooperates. |
| **Git hook mode** | `gitsage install-hooks` → `git commit` pre-fills the editor with an AI-generated message. Review and save. |
| **Any LLM** | DeepSeek, OpenAI, Anthropic, or a local Ollama model. Zero data through our servers. |

---

## Quick Start

### Install

```bash
pip install gitsage
```

### Configure

```bash
# Option A: local model (free, nothing leaves your machine)
ollama pull qwen2.5:14b
gitsage model set ollama/qwen2.5:14b

# Option B: cloud API (DeepSeek recommended — ~$0.001 per commit)
export DEEPSEEK_API_KEY=sk-...
gitsage model set deepseek-v4-flash
```

### Run

```bash
git add .
gitsage commit      # generate commit message, pick one, done
gitsage standup     # what did I do today?
gitsage explain src/auth/token.py  # why does this code exist?
```

---

## How It Works

gitsage operates in three layers:

```
┌──────────────────────────────────────────────────────────┐
│  Harness Layer  (deterministic rules, quality gates)      │
│  → enforces CTX.md rules regardless of LLM output        │
├──────────────────────────────────────────────────────────┤
│  Context Layer  (git state + project config + memory)     │
│  → staged diff, blame, history, CTX.md, learned style    │
├──────────────────────────────────────────────────────────┤
│  LLM Layer      (single call or agent loop)              │
│  → commit/standup: one structured call                   │
│  → explain/catchup: agent loop with tool use             │
└──────────────────────────────────────────────────────────┘
```

**Context is assembled locally.** Your code never goes through gitsage's servers — it goes directly from your machine to whichever LLM you configure.

---

## Commands

### Core

```bash
gitsage commit                    # generate commit message (interactive)
gitsage commit --mode print       # show candidates, don't commit
gitsage commit --mode execute     # silently commit the top candidate
gitsage commit --estimate         # show token cost before calling LLM

gitsage standup                   # today's work summary
gitsage standup --print           # plain text output (pipe-friendly)

gitsage pr                        # PR title + description for current branch
gitsage pr --base-branch develop  # compare against a specific branch

gitsage explain <file>            # why does this code exist?
gitsage explain <file> --local    # skip GitHub API, local git history only
```

### Configuration

```bash
gitsage setup                     # interactive LLM setup wizard
gitsage preferences               # set language, emoji, commit style…
gitsage preferences --show        # view current preferences
gitsage config init               # generate CTX.md template for this repo
gitsage config show               # show resolved configuration
```

### Model management

```bash
gitsage model list                # current model + suggestions
gitsage model set deepseek-v4-flash
gitsage model test                # verify the connection works
```

### Utility

```bash
gitsage doctor                    # check environment and configuration
gitsage install-hooks             # install prepare-commit-msg git hook
gitsage memory show               # view learned preferences for this repo
gitsage memory clear              # reset memory for this repo
gitsage skill list                # list available skills
```

---

## CTX.md — Project Conventions

Drop a `CTX.md` in your repo root (commit it so the whole team shares it):

```markdown
# CTX.md — Project Context

## Project Background
Payment service for the mobile app. Java + Spring Boot.
Core modules: order-service, payment-service, user-service.

## Commit Rules
Format: <emoji> <type>(<scope>): <description>
Language: Chinese
Example: ✨ feat(payment): 新增支付重试机制

## Standup Format
Audience: technical lead. Be concise, focus on impact.

## Rules
always:
  - Include JIRA ticket number from branch name [PAY-XXX]
  - Flag payment module changes with ⚠️
never:
  - Include file paths in commit messages
  - Mention implementation details in standups
```

No CTX.md? gitsage still works — outputs are just more generic.

---

## Memory System

gitsage observes your commits and builds a per-repo memory file:

```markdown
# ~/.gitsage/memory/Moyonx_gitsage_a1b2c3.md

## Learned Preferences (auto-updated)
- Commit style: imperative mood, English, no emoji
- Typical scope: cli, agent, harness
- Branch pattern: feat/PAY-XXX-description → always appends [PAY-XXX]

## Recent Context
- Currently working on: gitsage explain (code archaeology feature)
- Last major change: preferences system
```

Every 20 commits, an LLM pass condenses raw observations into structured preferences. The outputs get noticeably better after a week of regular use.

---

## Git Hook

```bash
gitsage install-hooks
```

After that, `git commit` pre-fills the editor with a generated message:

```
# Editor opens with:
feat(payment): add exponential backoff retry mechanism [PAY-234]

# You review, edit if needed, save → commit happens
# git commit -m "..." still works normally (hook skipped)
```

---

## Skills

Skills are markdown files that give gitsage domain-specific reasoning frameworks. They live in `.gitsage/skills/<name>/SKILL.md`.

```bash
gitsage skill list          # see installed skills
```

Example: a `jira-standup` skill that formats standups with JIRA ticket references, stored in `.gitsage/skills/jira-standup/SKILL.md`. The skill's description is always in context; the full content loads only when relevant.

---

## Supported Providers

| Provider | Setup | Notes |
|----------|-------|-------|
| **Ollama** | `ollama pull qwen2.5:14b` | Free, local, no data leaves machine |
| **DeepSeek** | `export DEEPSEEK_API_KEY=sk-...` | Recommended cloud option, ~$0.001/commit |
| **OpenAI** | `export OPENAI_API_KEY=sk-...` | Works with all OpenAI-compatible APIs |
| **Anthropic** | `export ANTHROPIC_API_KEY=sk-ant-...` | Best quality, higher cost |
| **Custom** | Set `base_url` in config | Any OpenAI-compatible endpoint |

```bash
# Switch providers anytime
gitsage model set deepseek-v4-flash
gitsage model set ollama/qwen2.5:14b
gitsage model test
```

---

## Configuration File

`~/.gitsage/config.yml` (global) or auto-detected from current directory:

```yaml
llm:
  provider: openai-compatible
  model: deepseek-v4-flash
  api_key: ${DEEPSEEK_API_KEY}      # env var expansion supported
  base_url: https://api.deepseek.com

commit:
  default_mode: interactive          # interactive | print | execute

preferences:
  language: auto                     # zh | en | auto
  commit_emoji: false
  commit_scope: true
  commit_length: standard            # brief | standard | detailed
  ticket_format: auto               # auto | jira | github | none
  standup_audience: technical        # technical | nontechnical
```

---

## Privacy

- **Your code never goes through gitsage.** It goes directly from your terminal to your configured LLM provider.
- **Ollama** = completely offline. Nothing leaves your machine.
- **Cloud providers** = your diff and commit history go to whichever API you configure (DeepSeek, OpenAI, etc.), subject to their own privacy policies.
- gitsage has no telemetry by default.

---

## Development

```bash
git clone https://github.com/Moyonx/gitsage
cd gitsage
pip install -e ".[dev]"

# Run tests
pytest

# Run with local changes
python -m gitsage commit
```

### Architecture

```
gitsage/
├── config.py          # configuration loading (ENV > ~/.gitsage/config.yml > CTX.md)
├── cli.py             # Typer CLI — all commands
├── wizard.py          # interactive setup wizard
├── preferences.py     # user preference survey and persistence
├── context/
│   ├── git_reader.py  # GitPython wrapper — staged diff, blame, history
│   ├── ctx_reader.py  # CTX.md parser — project conventions
│   ├── memory.py      # MEMORY.md — two-phase learning system
│   └── builder.py     # assembles context for LLM calls
├── agent/
│   ├── llm.py         # LLM abstraction — Anthropic SDK + OpenAI-compatible
│   ├── models.py      # Pydantic output models
│   └── prompts.py     # system prompts and user prompt builders
├── harness/
│   ├── quality_gate.py    # output validation and retry
│   ├── override.py        # deterministic rule enforcement
│   └── hooks.py           # lifecycle hook runner
├── skills/
│   └── loader.py      # SKILL.md discovery and loading
└── renderer/
    └── interactive.py # Rich-based commit selection UI
```

---

## Contributing

Pull requests welcome. For significant changes, open an issue first to discuss the approach.

```bash
# Run tests before submitting
pytest tests/
```

Skill contributions (new SKILL.md files for common workflows) are especially welcome.

---

## License

MIT — see [LICENSE](LICENSE).
