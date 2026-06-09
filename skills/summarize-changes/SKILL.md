---
name: summarize-changes
description: Summarize code changes from a Git diff or changed files, focusing on behavior, impact, and verification. Use when the user asks what changed, requests a concise change summary, or needs release-note-style bullets for local modifications.
---

# Summarize Changes

Inspect the relevant diff and changed files before writing the summary.

Report:

- What behavior changed.
- Which users or systems are affected.
- What validation was performed.
- Any important risk or limitation.

Prefer two to five concise bullets. Group related file edits by behavior instead of listing every file.

Do not claim tests passed unless their results were observed. If no diff or changed files are available, state that limitation instead of inventing a summary.
