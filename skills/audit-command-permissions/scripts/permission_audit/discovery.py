from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .redact import stable_id


@dataclass(frozen=True)
class LogSource:
    path: Path
    product: str
    kind: str
    source_id: str


def discover(codex_home: Path, claude_home: Path, since: datetime | None) -> list[LogSource]:
    sources: list[LogSource] = []
    sources.extend(
        make_sources(
            codex_home,
            ("sessions/**/*.jsonl", "archived_sessions/*.jsonl"),
            "codex",
            "codex_session",
            since,
        )
    )
    sources.extend(
        make_sources(
            claude_home,
            ("projects/**/*.jsonl",),
            "claude",
            "claude_project_session",
            since,
        )
    )
    return sorted(sources, key=lambda source: str(source.path))


def make_sources(
    root: Path,
    patterns: Iterable[str],
    product: str,
    kind: str,
    since: datetime | None,
) -> list[LogSource]:
    result = []
    if not root.exists():
        return result
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if since and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < since:
                continue
            result.append(
                LogSource(
                    path=path,
                    product=product,
                    kind=kind,
                    source_id=stable_id(product, str(path.resolve())),
                )
            )
    return result
