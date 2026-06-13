---
name: agmsg
description: Send and receive messages between Codex and Claude Code sessions through a shared local SQLite database. Use for cross-agent coordination, inbox checks, team membership, message history, role switching, delivery modes, and spawning peer agents.
license: MIT
compatibility: Requires bash and sqlite3. Supports Codex and Claude Code.
---

# Agent Messaging

Use the bundled scripts for every operation. Never read or edit the database,
team files, runtime files, or hook settings directly.

## Bootstrap

Set `SKILL_DIR` to the directory containing this file.

If `$SKILL_DIR/runtime-path` is missing, run:

```bash
bash "$SKILL_DIR/install.sh"
```

The installer locates the skills repository, initializes its ignored `.agmsg/`
directory, records the runtime path, and configures the Codex sandbox when
needed. If bootstrap fails, report the exact error and stop.

## Environment

Determine whether the current agent is Codex or Claude Code.

- Codex: read `SKILL.codex.md` before continuing.
- Claude Code: read `SKILL.claude-code.md` before continuing.
- If the environment cannot be determined, ask the user rather than guessing.

The environment file defines `AGENT_TYPE`, invocation syntax, delivery modes,
and environment-specific `actas` behavior.

## Identity

Run:

```bash
"$SKILL_DIR/scripts/whoami.sh" "$(pwd)" "$AGENT_TYPE"
```

Handle its output:

- `agent=... teams=...`: remember the identity for this session.
- `multiple=true ...`: ask which listed identity to use.
- `not_joined=true ...`: show available teams, then ask for a team name and
  agent name one at a time. Join with:

  ```bash
  "$SKILL_DIR/scripts/join.sh" <team> <agent> "$AGENT_TYPE" "$(pwd)"
  ```

  Then follow the environment file's first-run delivery-mode flow and check
  the new inbox.
- `suggest=true ...`: offer the existing same-type names, ask whether to reuse
  one, ask for a team, then run `join.sh`.

Do not invent or use a `register.sh` command.

## Commands

With no arguments, immediately check every team inbox:

```bash
"$SKILL_DIR/scripts/inbox.sh" <team> <agent>
```

Do not ask what action to take first. Respond appropriately to received
messages. Send replies with:

```bash
"$SKILL_DIR/scripts/send.sh" <team> <from-agent> <to-agent> "<message>"
```

Other operations:

```bash
"$SKILL_DIR/scripts/history.sh" <team> [agent]
"$SKILL_DIR/scripts/team.sh" <team>
"$SKILL_DIR/scripts/config.sh" show
"$SKILL_DIR/scripts/config.sh" set <key> <value>
"$SKILL_DIR/scripts/reset.sh" "$(pwd)" "$AGENT_TYPE" [agent] [session-id]
"$SKILL_DIR/scripts/spawn.sh" <claude-code|codex> <name> --project "$(pwd)" [options]
```

For `send`, determine which team contains the recipient before invoking the
script. Quote the message as one shell argument.

For `spawn`, pass through `--team`, `--window`, `--split`, and `--terminal`
options when requested. Show the script output. Spawning affects a separate
session and must not restart the current session's receiver.

Use the environment file for `actas`, `drop`, delivery `mode`, and legacy
`hook on|off` behavior.
