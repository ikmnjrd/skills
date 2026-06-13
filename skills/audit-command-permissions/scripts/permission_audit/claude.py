from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .common import in_scope, iso_timestamp, jsonl_records, make_project, project_matches
from .discovery import LogSource
from .models import OperationEvent, SourceRef
from .normalize import normalize_shell, summarize_tool_input


def extract_claude(
    source: LogSource,
    *,
    home: Path,
    since,
    project_filters: list[str],
    include_experimental: bool,
) -> list[OperationEvent]:
    events: list[OperationEvent] = []
    by_call_id: dict[str, OperationEvent] = {}

    for line, record in jsonl_records(source.path):
        timestamp = record.get("timestamp")
        if not in_scope(timestamp, since):
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        cwd_text = record.get("cwd") or record.get("project")
        project, cwd = make_project(cwd_text, home)
        if not project_matches(cwd, project_filters):
            continue

        if record.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool = str(block.get("name") or "unknown")
                call_id = str(block.get("id") or "")
                tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                command = tool_input.get("command")
                if tool == "Bash" and isinstance(command, str):
                    normalized = normalize_shell(command, cwd, home)
                    event = OperationEvent(
                        event_id=event_id(source.source_id, line, call_id),
                        product="claude",
                        timestamp=iso_timestamp(timestamp),
                        category="shell",
                        support_level="stable",
                        tool=tool,
                        project=project,
                        source=SourceRef(source.source_id, source.kind, line),
                        command=normalized["command"],
                        executable=normalized["executable"],
                        normalized_shape=normalized["normalized_shape"],
                        parse_status=normalized["parse_status"],
                        targets=normalized["targets"],
                        features=normalized["features"],
                        limitations=normalized["limitations"],
                        call_id=call_id or None,
                    )
                elif include_experimental:
                    targets, features = summarize_tool_input(tool, tool_input, cwd, home)
                    event = OperationEvent(
                        event_id=event_id(source.source_id, line, call_id),
                        product="claude",
                        timestamp=iso_timestamp(timestamp),
                        category="experimental",
                        support_level="experimental",
                        tool=tool,
                        project=project,
                        source=SourceRef(source.source_id, source.kind, line),
                        targets=targets,
                        features=features,
                        limitations=["non_shell_extraction_is_experimental"],
                        call_id=call_id or None,
                    )
                else:
                    continue
                events.append(event)
                if call_id:
                    by_call_id[call_id] = event

        if record.get("type") == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                call_id = str(block.get("tool_use_id") or "")
                if call_id in by_call_id:
                    by_call_id[call_id].outcome = infer_outcome(block)
    return events


def infer_outcome(block: dict[str, Any]) -> str:
    content = block.get("content")
    text = str(content).lower()
    if block.get("is_error") and any(
        marker in text for marker in ("permission", "denied", "rejected", "not approved")
    ):
        return "denied"
    return "executed-without-observed-decision"


def event_id(source_id: str, line: int, call_id: str) -> str:
    value = f"{source_id}:{line}:{call_id}"
    return "event_" + hashlib.sha256(value.encode()).hexdigest()[:16]
