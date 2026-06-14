#!/usr/bin/env python3
"""agmsg — agent-to-agent messaging CLI.

Usage:
    python3 agmsg.py [--json] <command> [args...]

Run ``python3 agmsg.py help`` for the command list. See SKILL.md for the
full contract. This single entry point replaces the previous shell scripts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agmsg_cli.commands import COMMANDS  # noqa: E402
from agmsg_cli.envelope import AgmsgError, emit, emit_error  # noqa: E402

HELP = (
    "agmsg — agent-to-agent messaging\n\n"
    "Usage: python3 agmsg.py [--json] <command> [args...]\n\n"
    "Commands:\n"
    "  install [--repo-root P] [--skill-dir P] [--reset]\n"
    "  whoami <project> [type]\n"
    "  join <team> <agent> <type> <project>\n"
    "  leave <team> <agent>\n"
    "  inbox <team> <agent> [--quiet]\n"
    "  send <team> <from> <to> <message>\n"
    "  history <team> [agent] [limit]\n"
    "  team <team>\n"
    "  rename <team> <old> <new>\n"
    "  rename-team <old> <new>\n"
    "  reset <project> <type> [agent] [session]\n"
    "  spawn <claude-code|codex> <name> [--project P] [--team T] [--window] [--split h|v]\n"
    "  config show|get <key> [default]|set <key> <value>\n"
    "  delivery set <mode> <type> <project> | status <type> <project> | stop | restart\n"
    "  actas <name> [--project P] [--type T] [--team T]\n"
    "  drop <name> [--project P] [--type T]\n"
)


def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = False
    # --json is a GLOBAL flag: recognized only before the command. A literal
    # "--json" appearing among a command's arguments (e.g. a message body) is
    # preserved untouched.
    while args and args[0] == "--json":
        as_json = True
        args = args[1:]

    if not args or args[0] in ("help", "-h", "--help"):
        sys.stdout.write(HELP)
        return 0

    command = args[0]
    rest = args[1:]
    handler = COMMANDS.get(command)
    if handler is None:
        err = AgmsgError("unknown_command", f"Unknown command: {command}", 2)
        return emit_error(command, err, as_json)

    try:
        result = handler(rest, as_json)
    except AgmsgError as exc:
        return emit_error(command, exc, as_json)
    except BrokenPipeError:
        return 0

    if isinstance(result, int):
        return result
    emit(command, result.get("data"), result.get("human", ""), as_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
