"""Output envelope + error type shared by every command.

Human mode prints plain text. ``--json`` mode prints a common envelope:
    {"schema_version": 1, "ok": true, "command": "...", "data": {...}}
On failure:
    {"schema_version": 1, "ok": false, "command": "...",
     "error": {"code": "...", "message": "..."}}
and the process exits non-zero.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import SCHEMA_VERSION


class AgmsgError(Exception):
    """A command failure carrying a stable error code + exit status."""

    def __init__(self, code: str, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


def emit(command: str, data: Any, human: str, as_json: bool) -> None:
    """Print a successful result in the selected format."""
    if as_json:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "command": command,
            "data": data,
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    elif human:
        sys.stdout.write(human if human.endswith("\n") else human + "\n")


def emit_error(command: str, err: AgmsgError, as_json: bool) -> int:
    """Print a failure in the selected format; return the exit code."""
    if as_json:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "command": command,
            "error": {"code": err.code, "message": err.message},
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    else:
        sys.stderr.write(f"agmsg {command}: {err.message}\n")
    return err.exit_code
