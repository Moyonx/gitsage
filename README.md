# gitsage

> Git-native AI developer workflow assistant.
> 理解你在做什么、帮你表达出来、记住你的习惯。

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it does

```bash
gitsage commit      # Generate commit message from staged diff
gitsage standup     # Summarize today's work for standups
gitsage pr          # Generate PR description from branch diff
gitsage explain     # Explain why code exists using git history
gitsage catchup     # Catch up on recent repo changes
```

**Not just another AI wrapper.** gitsage builds context from three layers:
- **CTX.md** — your project's conventions (committed to git, shared with team)
- **Memory** — learns your style over time, gets smarter with use
- **Harness** — quality gates and deterministic rules ensure consistent output

## Quick Start

```bash
pip install gitsage

# Set up your API key
export DEEPSEEK_API_KEY=sk-...   # or ANTHROPIC_API_KEY / OPENAI_API_KEY

# Initialize project context (analyzes your git history)
gitsage config init

# Generate a commit message
git add .
gitsage commit
```

## Supported LLM Providers

| Provider | Notes |
|----------|-------|
| DeepSeek | Recommended — best quality/cost ratio |
| Anthropic | Best quality |
| OpenAI | |
| Ollama | 100% local, no data leaves your machine |

## Documentation

See [docs/design.md](docs/design.md) for full design documentation.
