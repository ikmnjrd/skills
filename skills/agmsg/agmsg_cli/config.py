"""JSON machine configuration (``config.json`` in the runtime dir).

Replaces the old ``config.yaml``. Dotted keys index nested objects, e.g.
``delivery.monitor.poll_interval``. There is intentionally no global delivery
"mode" key — mode is derived per project from the hook files by ``delivery``.
"""
from __future__ import annotations

import json
from typing import Any

from . import SCHEMA_VERSION
from . import platform as plat
from .envelope import AgmsgError
from .jsonio import atomic_write_json


def default_config() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "delivery": {
            # watch SQLite poll interval, seconds
            "monitor": {"poll_interval": 5},
            # Stop-hook cooldown, seconds
            "turn": {"check_interval": 60},
        },
    }


def load() -> dict:
    """Load config.json. Missing -> defaults. A present-but-corrupt file (read
    error, invalid JSON, or non-object root) is a hard error so ``config set``
    never silently overwrites it."""
    path = plat.config_path()
    if not path.is_file():
        return default_config()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgmsgError("config_read_error", f"cannot read {path}: {exc}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AgmsgError(
            "config_parse_error",
            f"{path} is not valid JSON; refusing to modify it ({exc}).",
        )
    if not isinstance(data, dict):
        raise AgmsgError(
            "config_type_error",
            f"{path} must be a JSON object, got {type(data).__name__}.",
        )
    return data


def save(data: dict) -> None:
    atomic_write_json(plat.config_path(), data, error_code="config_write_error")


def ensure_exists() -> None:
    if not plat.config_path().is_file():
        save(default_config())


def _coerce(value: str) -> Any:
    """Coerce a string value to int/float/bool where it round-trips cleanly."""
    if value in ("true", "false"):
        return value == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def get(key: str, default: Any = None) -> Any:
    node: Any = load()
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def get_int(key: str, default: int) -> int:
    value = get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def set_value(key: str, value: str) -> Any:
    data = load()
    parts = key.split(".")
    if not parts or any(p == "" for p in parts):
        raise AgmsgError("bad_key", f"Invalid config key: '{key}'")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    coerced = _coerce(value)
    node[parts[-1]] = coerced
    save(data)
    return coerced


def show_text() -> str:
    return json.dumps(load(), indent=2, ensure_ascii=False)
