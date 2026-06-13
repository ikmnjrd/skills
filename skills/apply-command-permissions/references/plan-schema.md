# Application Plan Schema

Use schema version `1.0`.

```json
{
  "schema_version": "1.0",
  "plan_id": "plan-unique-id",
  "created_at": "2026-06-13T00:00:00Z",
  "rules": [
    {
      "id": "ACP-ALLOW-001",
      "product": "codex",
      "action": "add",
      "decision": "allow",
      "pattern": ["cargo", "test", "-p", "example"],
      "scope": "user",
      "source": "audit-candidate",
      "observed": true,
      "global_effect_confirmed": true,
      "reason": "Exact project test command",
      "match": [["cargo", "test", "-p", "example"]],
      "not_match": [
        ["cargo", "install", "example"],
        ["cargo", "test", "--workspace"]
      ],
      "relation_evidence": []
    }
  ]
}
```

Claude patterns are strings:

```json
{
  "id": "ACP-FORBID-002",
  "product": "claude",
  "action": "add",
  "decision": "deny",
  "pattern": "Bash(git push * --force *)",
  "scope": "project-local",
  "project_path": "/workspace/example",
  "source": "user-policy",
  "observed": false,
  "reason": "Never force-push from the agent",
  "match": ["Bash(git push origin main --force)"],
  "not_match": ["Bash(git push origin main)", "Bash(git status)"]
}
```

## Replace

`replace` requires `old_rule`, containing the exact existing decision and
pattern. It is evaluated as exact removal followed by addition.

## Relation Evidence

```json
{
  "existing": "Bash(git *)",
  "proposed": "Bash(git push *)",
  "relation": "subset",
  "subset": "proposed",
  "superset": "existing",
  "evaluator": "claude-local",
  "cases": [
    {
      "command": "Bash(git push origin main)",
      "existing": true,
      "proposed": true
    },
    {
      "command": "Bash(git status)",
      "existing": true,
      "proposed": false
    }
  ],
  "test_code_hash": "sha256...",
  "result_hash": "sha256..."
}
```

Directional `subset` requires a case that matches both rules and a case that
matches only the superset. `disjoint` also requires a `proof` string explaining
why the product grammar makes intersection impossible.

Allowed relations:

- `equivalent`
- `subset`, with direction
- `overlap`
- `disjoint`
- `unresolved`

`unresolved` blocks application.

`result_hash` is SHA-256 of canonical JSON containing `relation`, `evaluator`,
`cases`, and any `subset`, `superset`, or `proof` fields. `test_code_hash`
identifies the temporary test code used to generate those cases.

## Strong Confirmation

Dangerous relaxation requires:

```json
{
  "requires_strong_confirmation": true,
  "strong_confirmation": {
    "confirmed": true,
    "summary": "Remove deny X; operation Y becomes possible.",
    "summary_hash": "SHA-256 of summary"
  }
}
```
