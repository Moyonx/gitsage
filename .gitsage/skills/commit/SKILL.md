---
name: commit
description: Generate git commit messages following project conventions
trigger: auto
---

## Reasoning Steps

1. Analyze staged diff — identify the INTENT, not just what files changed
2. Cross-check against CTX.md commit conventions
3. Extract JIRA/ticket number from branch name (if pattern matches)
4. Generate primary candidate + 2 alternatives
5. Assign confidence and reasoning to each candidate

## Output Format

Return structured JSON:
{
  "candidates": [
    {
      "message": "feat(payment): add retry mechanism with exponential backoff",
      "confidence": "high",
      "reason": "Clear intent from diff, matches project conventions"
    },
    {
      "message": "feat: add payment retry logic",
      "confidence": "medium",
      "reason": "Missing module scope"
    }
  ],
  "warning": null
}

## Guidelines

- Extract purpose from diff, don't list filenames
- If changes span multiple unrelated modules, suggest splitting
- Set confidence to "low" when diff intent is unclear
- warning field: use when commit should be split or something unusual detected
