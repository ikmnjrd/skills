# Vendor metadata

Upstream: https://github.com/ikmnjrd/agmsg
Author: fujibee
Original path: repository root
Imported ref: 13815c1f7614a8e6b6689fda42976bce5d127fbc
Retrieved: 2026-06-18
License: MIT

## Attribution

The messaging implementation is vendored from agmsg. The upstream license is
preserved at:

- `../../LICENSES/agmsg-LICENSE`

## Local changes

- Re-implemented the entire skill in Python (standard library only, 3.11+):
  a single `agmsg.py` entry point backed by the `agmsg_cli/` package replaces
  the whole shell script set. No `.sh` files remain.
- Messages stay in SQLite; configuration and team registration use JSON.
- The CLI is non-interactive and offers a `--json` common envelope
  (`schema_version`, `ok`, `command`, `data`; on failure `error.code/message`
  and a non-zero exit).
- Consolidated hook generation, environment/identity/delivery detection,
  `actas`/`drop`, and install into the CLI.
- Dropped legacy `hook on|off`, the Gemini/Antigravity/Copilot agents, Windows
  support, free-form terminal templates, and generated shell.
- Reworked the project into a conventional Agent Skill.
- Split common instructions from Codex and Claude Code differences.
- Store mutable state in the host skills repository's ignored `.agmsg/`.
- Idempotent installer that records absolute Python + `agmsg.py` paths for
  hooks and refuses to migrate an old shell-era runtime without `--reset`.
- Localized the complete Markdown skill instructions for Japanese-language
  use while preserving commands and machine-readable identifiers.
- Added bounded incremental inbox polling when turn-mode work is blocked on a
  peer response.
- Added a maintenance README defining common and environment-specific document
  ownership.
- Added a unittest unit/integration suite under `tests/`.
- Ported upstream's Codex monitor bridge beta to the standard-library Python
  implementation. The single CLI now provides one-shot unread detection,
  stdio and WebSocket-over-Unix app-server clients, serialized turn delivery,
  watchdog re-arming, the outside-sandbox launcher rendezvous, explicit
  monitor launch, and a generated Python Codex shim.
- Added Codex monitor health reporting, stale bridge cleanup, and a Stop-hook
  fallback so sessions that were not launched through the shim still receive
  messages between turns instead of failing silently.
- Added Codex Desktop bridge startup from the first Stop hook. It uses the
  Desktop-provided thread ID and a detached app-server, allowing real-time
  delivery without requiring the CLI shim.

## Update policy

- Review upstream changes before importing them.
- Keep attribution and the upstream license intact.
- Reapply and test runtime-path separation after every update.
