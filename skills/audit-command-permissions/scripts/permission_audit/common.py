from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import ProjectRef
from .redact import stable_id


def jsonl_records(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield line_number, value


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_timestamp(value: Any) -> str | None:
    parsed = parse_timestamp(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def in_scope(timestamp: Any, since: datetime | None) -> bool:
    if since is None:
        return True
    parsed = parse_timestamp(timestamp)
    return parsed is None or parsed >= since


def make_project(cwd: str | None, home: Path) -> tuple[ProjectRef, Path]:
    path = Path(cwd).expanduser() if cwd else home
    resolved = path.resolve(strict=False)
    name = resolved.name or "filesystem-root"
    display = str(resolved).replace(str(home), "<HOME>", 1)
    return (
        ProjectRef(
            project_id=stable_id("project", str(resolved)),
            name=name,
            display_path=display,
        ),
        resolved,
    )


def project_matches(cwd: Path, filters: list[str]) -> bool:
    if not filters:
        return True
    text = str(cwd)
    return any(item in text or item == cwd.name for item in filters)
