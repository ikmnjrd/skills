from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .claude import extract_claude
from .codex import extract_codex
from .discovery import discover


@dataclass
class AuditOptions:
    codex_home: Path
    claude_home: Path
    since: datetime | None
    project_filters: list[str]
    include_experimental: bool

    @classmethod
    def from_args(cls, args) -> "AuditOptions":
        if args.all_time:
            since = None
        elif args.since:
            text = args.since.replace("Z", "+00:00")
            since = datetime.fromisoformat(text)
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            since = since.astimezone(timezone.utc)
        else:
            since = datetime.now(timezone.utc) - timedelta(days=90)
        return cls(
            codex_home=args.codex_home.expanduser(),
            claude_home=args.claude_home.expanduser(),
            since=since,
            project_filters=args.project,
            include_experimental=not args.shell_only,
        )


def run_audit(options: AuditOptions) -> dict[str, Any]:
    sources = discover(options.codex_home, options.claude_home, options.since)
    events = []
    errors = []
    home = Path.home()

    for source in sources:
        try:
            if source.product == "codex":
                extracted = extract_codex(
                    source,
                    home=home,
                    since=options.since,
                    project_filters=options.project_filters,
                    include_experimental=options.include_experimental,
                )
            else:
                extracted = extract_claude(
                    source,
                    home=home,
                    since=options.since,
                    project_filters=options.project_filters,
                    include_experimental=options.include_experimental,
                )
            events.extend(extracted)
        except OSError as error:
            errors.append({"source_id": source.source_id, "error": type(error).__name__})

    events.sort(key=lambda event: (event.timestamp or "", event.event_id))
    event_dicts = [event.to_dict() for event in events]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": {
            "since": options.since.isoformat().replace("+00:00", "Z") if options.since else None,
            "all_time": options.since is None,
            "project_filters": options.project_filters,
            "experimental_enabled": options.include_experimental,
        },
        "summary": summarize(event_dicts, len(sources), errors),
        "groups": group_events(event_dicts),
        "cross_project_groups": group_events_cross_project(event_dicts),
        "events": event_dicts,
        "errors": errors,
        "limitations": [
            "Approval outcomes are recorded only when explicit evidence is present.",
            "approved is an observation, never a safety classification.",
            "Non-shell extraction is experimental and is not a permission-rule proposal.",
            "Original commands and absolute source paths are not retained.",
        ],
    }


def summarize(events: list[dict], source_count: int, errors: list[dict]) -> dict:
    categories = Counter(event["category"] for event in events)
    products = Counter(event["product"] for event in events)
    outcomes = Counter(event["outcome"] for event in events)
    return {
        "sources_scanned": source_count,
        "source_errors": len(errors),
        "total_events": len(events),
        "shell_events": categories["shell"],
        "experimental_events": categories["experimental"],
        "products": dict(sorted(products.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "unique_projects": len({event["project"]["project_id"] for event in events}),
    }


def group_events(events: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for event in events:
        if event["category"] == "shell":
            key = (
                "shell",
                event["project"]["project_id"],
                event.get("normalized_shape"),
            )
        else:
            key = (
                "experimental",
                event["project"]["project_id"],
                event["tool"],
                tuple(event.get("features", [])),
            )
        grouped[key].append(event)

    result = []
    for key, members in grouped.items():
        first = members[0]
        result.append(
            {
                "category": first["category"],
                "support_level": first["support_level"],
                "project": first["project"],
                "tool": first["tool"],
                "normalized_shape": first.get("normalized_shape"),
                "observed": len(members),
                "products": dict(sorted(Counter(item["product"] for item in members).items())),
                "outcomes": dict(sorted(Counter(item["outcome"] for item in members).items())),
                "features": sorted(
                    {feature for item in members for feature in item.get("features", [])}
                ),
                "examples": [item.get("command") for item in members if item.get("command")][:3],
                "event_ids": [item["event_id"] for item in members],
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["category"],
            item["project"]["project_id"],
            item.get("normalized_shape") or item["tool"],
        ),
    )


def group_events_cross_project(events: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for event in events:
        if event["category"] == "shell":
            key = ("shell", event.get("normalized_shape"))
        else:
            key = ("experimental", event["tool"], tuple(event.get("features", [])))
        grouped[key].append(event)

    result = []
    for members in grouped.values():
        first = members[0]
        projects = {
            item["project"]["project_id"]: item["project"]["name"] for item in members
        }
        result.append(
            {
                "category": first["category"],
                "support_level": first["support_level"],
                "tool": first["tool"],
                "normalized_shape": first.get("normalized_shape"),
                "observed": len(members),
                "project_count": len(projects),
                "projects": [
                    {"project_id": project_id, "name": name}
                    for project_id, name in sorted(projects.items())
                ],
                "features": sorted(
                    {feature for item in members for feature in item.get("features", [])}
                ),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["category"],
            item.get("normalized_shape") or item["tool"],
        ),
    )
