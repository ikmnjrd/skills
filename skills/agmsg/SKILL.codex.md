# Codex Behavior

Set:

```text
AGENT_TYPE=codex
INVOCATION=$agmsg
```

Codex supports delivery modes `turn` and `off`. It has no Monitor tool; reject
`monitor` and `both`.

After first join, ask the user to choose:

```text
Choose delivery mode for incoming messages:

  1) turn - Check inbox at the end of each assistant turn.
  2) off  - No automatic delivery; manual $agmsg only.

[1]:
```

Wait for the answer. Empty input means `turn`. Apply it with:

```bash
"$SKILL_DIR/scripts/delivery.sh" set <turn|off> codex "$(pwd)"
```

## Roles

For `actas <name>`:

1. Check `identities.sh "$(pwd)" codex`.
2. If absent, join the role to the current team. Ask which team if there are
   multiple.
3. Use `<name>` as the sender for this session.
4. Receiving still covers every registered role because Codex has no Monitor.

For `drop <name>`, run:

```bash
"$SKILL_DIR/scripts/reset.sh" "$(pwd)" codex <name>
```

Clear the active sender if it was dropped.

## Delivery

For `mode`, show:

```bash
"$SKILL_DIR/scripts/delivery.sh" status codex "$(pwd)"
```

For `mode turn|off`, set the requested mode. `hook on` maps to `turn`; `hook
off` maps to `off`.
