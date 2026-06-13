---
name: apply-command-permissions
description: Safely apply user-selected permission rules to Codex and Claude Code after reviewing audit candidates. Use when the user asks to apply, add, remove, replace, migrate, dry-run, validate, or roll back Codex execpolicy rules or Claude Code allow/ask/deny permissions. Requires explicit candidate selection, dry-run review, confirmation IDs, conflict resolution, backups, validation, and product-by-product application.
---

# Apply Command Permissions

Convert the user's selected candidates into an application plan, dry-run each
product, obtain explicit confirmation, and invoke the bundled CLI. Never apply
rules directly with ad hoc file edits.

## Boundaries

- Apply one product per write operation.
- Do not infer selection from an earlier audit report. Require candidate IDs or
  an equally explicit list.
- Do not apply experimental Codex non-shell permissions.
- Permit unobserved `ask/prompt` and `deny/forbidden` rules when they are
  explicit user policy. Reject unobserved `allow`.
- Stop on unresolved conflicts, invalid settings, stale dry-runs, failed tests,
  or missing Codex official validation.
- Never use a force flag to bypass confirmation, conflicts, or rollback guards.

## Workflow

### 1. Resolve the Selection

Identify selected candidate IDs such as `ACP-ALLOW-001`. For every rule resolve:

- Product: `codex` or `claude`.
- Action: `add`, `remove`, or `replace`.
- Decision and exact pattern.
- Claude scope: `user`, `project`, or `project-local`.
- Source: `audit-candidate` or `user-policy`.
- Reason and observed status.
- Match and not-match cases.

Codex is user-scoped. Warn that every Codex rule affects all projects. Do not
apply a project-specific Codex allow unless the user explicitly accepts the
global effect.

### 2. Create the Plan

Read [plan-schema.md](references/plan-schema.md). Create the plan under `/tmp`
with mode `0600`; do not include chat transcripts or secrets.

For ambiguous overlap:

1. Inspect the installed product rules and current official semantics.
2. Generate temporary tests under `/tmp`.
3. Prefer the official product evaluator.
4. Classify the relation as `equivalent`, directional `subset`, `overlap`,
   `disjoint`, or `unresolved`.
5. Record cases, evaluator, test-code hash, and result hash in the plan.
6. Stop if unresolved.

### 3. Dry-Run

Run:

```bash
python3 scripts/apply_command_permissions.py dry-run \
  --plan /tmp/apply-command-permissions-plan.json \
  --product codex
```

Dry-run reports:

- Target product, scope, and files.
- Current and proposed hashes.
- Adds, removals, replacements, and no-ops.
- Conflicts and relation evidence.
- Match and not-match results.
- Unified diff and retained unrelated settings.
- Backup name and `confirmation_id`.

Resolve all reported blockers before continuing.

### 4. Confirm

Show the user the exact dry-run. Require a clear affirmative response.

For dangerous relaxation, separately restate the removed protection and its
effect. Put the exact restatement and its SHA-256 hash into
`strong_confirmation`. A generic "apply it" is insufficient for:

- Removing or weakening deny/forbidden.
- Changing ask/prompt to allow.
- Broadening a rule.
- Bulk removal.

### 5. Apply

After confirmation, run the same plan with the dry-run confirmation ID:

```bash
python3 scripts/apply_command_permissions.py apply \
  --plan /tmp/apply-command-permissions-plan.json \
  --product codex \
  --confirmation-id CONFIRMATION_ID
```

The CLI rechecks current hashes, tests, confirmation evidence, and merged
content. It backs up, writes atomically, verifies, and rolls back automatically
on failure.

Apply the other product only through a separate dry-run and apply cycle.

### 6. Finish

On success:

- Report files changed, backup ID, and validation result.
- Remove the temporary plan.
- Note that durable records live under
  `~/workspace/apply-command-permissions-log/{codex|claude}/`.

On failure, leave the plan in place and report its path.

### Rollback

List recent operations:

```bash
python3 scripts/apply_command_permissions.py status --product codex
```

Rollback only when the current file hash matches the selected operation's
post-apply hash:

```bash
python3 scripts/apply_command_permissions.py rollback \
  --product codex \
  --operation-id OPERATION_ID
```

If later changes exist, create a new inverse plan instead. Never force an old
backup over newer changes.
