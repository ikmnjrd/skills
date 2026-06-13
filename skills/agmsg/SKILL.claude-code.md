# Claude Code Behavior

Set:

```text
AGENT_TYPE=claude-code
INVOCATION=/agmsg
```

Claude Code supports `monitor`, `turn`, `both`, and `off`.

After first join, ask the user to choose:

```text
Choose delivery mode for incoming messages:

  1) monitor - Real-time push through the Monitor tool. Recommended.
  2) turn    - Check inbox at the end of each assistant turn.
  3) both    - Monitor primary, turn fallback.
  4) off     - No automatic delivery; manual /agmsg only.

[1]:
```

Wait for the answer. Empty input means `monitor`. Apply it with:

```bash
"$SKILL_DIR/scripts/delivery.sh" set <mode> claude-code "$(pwd)"
```

Follow every `AGMSG-DIRECTIVE` emitted by `delivery.sh`.

Before processing a command, ensure an `agmsg inbox stream` Monitor is running
when the mode is `monitor` or `both`. Start it with:

```text
command: "$SKILL_DIR/scripts/watch.sh" "$CLAUDE_CODE_SESSION_ID" "$(pwd)" claude-code
description: agmsg inbox stream
persistent: true
```

## Roles

For `actas <name>`:

1. Check `identities.sh "$(pwd)" claude-code`.
2. If absent, join the role to the current team. Ask which team if needed.
3. Claim it with:

   ```bash
   "$SKILL_DIR/scripts/actas-claim.sh" "$(pwd)" claude-code <name> "$CLAUDE_CODE_SESSION_ID"
   ```

4. Abort on `status=held`; report the owner session.
5. Stop the existing `agmsg inbox stream` Monitor if one exists. Never guess a
   task ID.
6. Start a persistent Monitor with `<name>` as the fourth `watch.sh` argument.
7. Use `<name>` as sender and receive only that role's messages.

For `drop <name>`:

1. Run:

   ```bash
   "$SKILL_DIR/scripts/reset.sh" "$(pwd)" claude-code <name> "$CLAUDE_CODE_SESSION_ID"
   ```

2. Stop the current agmsg Monitor if present.
3. Restart the default unfiltered Monitor.
4. Clear the active sender if it was dropped.

## Delivery

For `mode`, show the `delivery.sh status` output. For `mode <name>`, set the
mode and follow its directive. `hook on` maps to `turn`; `hook off` maps to
`off`.
