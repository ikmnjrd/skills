# Rule Formats

These are output templates, not authority. Product syntax changes. Verify
against the locally installed version or current official documentation before
presenting final snippets.

## Codex

Codex rule proposals normally use `prefix_rule` entries:

```python
prefix_rule(
    pattern = ["cargo", "test", "-p", "example"],
    decision = "allow",
    justification = "Runs the exact local test target observed in the audit",
    match = [
        "cargo test -p example",
    ],
    not_match = [
        "cargo test --workspace",
        "cargo install example",
    ],
)
```

Decisions:

- `allow`
- `prompt`
- `forbidden`

Use argument-vector prefixes, not shell-text approximations. Remember that a
prefix permits trailing arguments, so shorten it only when all possible
trailing arguments remain acceptable. Include `match` and `not_match` examples.

## Claude Code

Claude Code proposals normally use permission arrays:

```json
{
  "permissions": {
    "allow": [
      "Bash(cargo test -p example)"
    ],
    "ask": [
      "Bash(git push *)"
    ],
    "deny": [
      "Bash(git push * --force *)"
    ]
  }
}
```

Decisions:

- `allow`
- `ask`
- `deny`

Rules may use wildcards and are sensitive to spaces and command structure.
Avoid broad forms such as `Bash(npm *)`, `Bash(git *)`, interpreter prefixes,
or execution wrappers. State test examples alongside the snippet even when the
configuration format cannot embed them.

## Cross-Product Translation

Do not claim the two rule languages are equivalent:

- Codex primarily matches argument-vector prefixes.
- Claude Code Bash rules match command patterns and may treat compound commands
  and wrappers specially.

Generate the narrowest independently valid rule for each product. If one
product cannot express the boundary, omit its allow rule and retain approval.
