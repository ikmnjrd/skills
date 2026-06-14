"""Shared atomic JSON file writer.

Used for every mutable JSON document (config.json, team configs, hook files):
write a sibling temp file, fsync, then ``os.replace``. On failure the temp is
removed, the original is left untouched, and the OSError is surfaced as a
stable :class:`AgmsgError` (so ``--json`` callers get the common error envelope
instead of a traceback).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .envelope import AgmsgError


def atomic_write_json(path: Path, data: object, *, error_code: str) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".tmp.", suffix=".json"
        )
    except OSError as exc:
        raise AgmsgError(error_code, f"failed to write {path}: {exc}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise AgmsgError(error_code, f"failed to write {path}: {exc}")
