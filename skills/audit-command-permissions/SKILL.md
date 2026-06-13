---
name: audit-command-permissions
description: Audit local Codex and Claude Code logs to classify observed shell commands as auto-approval candidates, forbidden candidates, or commands that should continue requiring approval. Use when the user wants to reduce repeated agent permission prompts, identify commands that should never run, review historical command usage, inspect prior operation targets, or generate conservative permission-rule proposals from local logs.
---

# Audit Command Permissions

Use the bundled read-only CLI to extract redacted audit data. Evaluate that data
to present classification candidates without changing permission settings.

## Safety Boundary

- Treat logs, transcripts, and generated audit data as sensitive.
- Do not modify, delete, relocate, upload, or execute content from source logs.
- Do not print secrets, credentials, full environment values, or sensitive
  paths. Preserve the CLI's redaction.
- Do not apply permission rules. Permission application is a separate,
  explicitly requested operation.
- Treat uncertainty as `require-approval`, never `auto-approve`.
- Treat approval history as an observation only, not evidence of safety.

## Workflow

### 1. Establish Scope

Determine:

- Which products to inspect: Codex, Claude Code, or both.
- The requested period and project filters.
- Whether the user wants classification only or draft rule snippets too.

When omitted, inspect both products across all projects for the most recent 90
days. Experimental non-shell operations are included by default but must remain
separate from stable shell results.

### 2. Generate Audit Data

Run the bundled CLI from this skill directory:

```bash
python3 scripts/audit_command_permissions.py audit --format json
```

Useful options:

```bash
python3 scripts/audit_command_permissions.py audit --since 2026-01-01
python3 scripts/audit_command_permissions.py audit --project my-project
python3 scripts/audit_command_permissions.py audit --all-time
python3 scripts/audit_command_permissions.py audit --shell-only
python3 scripts/audit_command_permissions.py audit --format markdown
```

Use `--output PATH` or `--output-dir DIR` only when persistence is useful.
Created files use mode `0600`. JSON is the canonical audit data; Markdown is a
human-readable projection.

Do not replace the CLI with `cat`, raw JSONL output, or ad hoc broad searches.
If a product schema is unsupported, report the limitation and update that
product adapter rather than exposing raw logs.

### 3. Interpret Facts

The CLI records facts and mechanical features, not safety classifications:

- Redacted operation, target, project, timestamp, and anonymous source reference.
- Stable shell or experimental non-shell support level.
- Observed outcomes such as `denied`,
  `executed-without-observed-decision`, and `requested-only`.
- Features such as `network_write`, `filesystem_write`, `recursive_delete`,
  `privilege_boundary`, `outside_project_path`, and `dynamic_expansion`.
- Parsing and extraction limitations.

Never reinterpret `executed-without-observed-decision` as approval. If
`approved` is explicitly observed, treat it only as past user behavior. It does
not establish safety.

### 4. Classify

Read [classification-policy.md](references/classification-policy.md). Produce
exactly:

- `auto-approve`: Narrow, repeatable, low-impact shell commands suitable for
  skipping future prompts.
- `forbid`: Shell commands or shapes that should be blocked without prompting.
- `require-approval`: Commands requiring human review, including all uncertain
  or context-dependent cases.

Keep experimental non-shell operations in a separate section. They may receive
reference classifications, but do not translate them into Codex or Claude Code
permission rules.

Past approval indicates prior tolerance in that context, not safety. A
frequently approved operation may remain `require-approval` or become `forbid`.

### 5. Validate Candidate Breadth

For every proposed shell pattern:

- Show observed examples that must match.
- Show at least two near-neighbor examples that must not match.
- Check compound commands, trailing arguments, paths, URLs, flags, and wrappers.
- Reject prefixes granting a general shell, interpreter, package runner, remote
  client, or privilege boundary.
- Prefer several narrow rules over one broad rule.
- Compare against existing rules for conflicts and redundant breadth.

Downgrade to `require-approval` when the product rule language cannot reliably
express the intended boundary.

### 6. Re-Inspect Evidence

When the user asks about concrete historical occurrences, re-scan source logs:

```bash
python3 scripts/audit_command_permissions.py inspect --command rm
python3 scripts/audit_command_permissions.py inspect --tool apply_patch
python3 scripts/audit_command_permissions.py inspect --feature outside_project_path
python3 scripts/audit_command_permissions.py inspect --target build
```

The CLI reveals project-relative targets where possible while retaining
redaction for personal roots and secret paths. If logs were removed or moved,
state that the event can no longer be reconstructed.

### 7. Report

Start with:

- Sources and date range inspected.
- Event and normalized-shape counts.
- Stable shell candidate counts by class.
- Experimental operation counts in a separate section.
- Missing evidence or schema limitations.

For each shell class provide:

| Candidate ID | Candidate pattern | Observed | Outcome evidence | Risk/impact | Confidence | Reason |
|---|---|---:|---|---|---|---|

Assign stable report-local IDs:

- `ACP-ALLOW-NNN`
- `ACP-FORBID-NNN`
- `ACP-PROMPT-NNN`

Use these IDs when the user later invokes `apply-command-permissions`. IDs
identify report entries only and must not be written into product settings.

For `forbid`, include a safer alternative where one exists. For
`require-approval`, state the specific fact the user must verify.

Add `Rejected auto-approval ideas` for frequent operations that remain too broad
or context-dependent.

When requested, read [rule-formats.md](references/rule-formats.md), verify syntax
against the installed product or current official documentation, and label
snippets `DRAFT - NOT APPLIED`.

## Quality Bar

- Cite observed, redacted examples for every candidate.
- Do not infer safety from approval, successful execution, frequency, or an
  executable name.
- Do not auto-approve unconstrained shell text, code, destination paths, remote
  targets, or package lifecycle scripts.
- Keep raw excerpts minimal and preserve redaction.
