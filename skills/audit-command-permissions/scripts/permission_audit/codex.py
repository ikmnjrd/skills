from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .common import (
    in_scope,
    iso_timestamp,
    jsonl_records,
    make_project,
    parse_json_object,
    project_matches,
)
from .discovery import LogSource
from .models import OperationEvent, SourceRef
from .normalize import SHELL_TOOLS, normalize_shell, summarize_tool_input


def extract_codex(
    source: LogSource,
    *,
    home: Path,
    since,
    project_filters: list[str],
    include_experimental: bool,
) -> list[OperationEvent]:
    events: list[OperationEvent] = []
    by_call_id: dict[str, OperationEvent] = {}
    current_cwd: str | None = None

    for line, record in jsonl_records(source.path):
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        record_type = record.get("type")
        payload_type = payload.get("type")
        timestamp = record.get("timestamp") or payload.get("timestamp")

        if record_type in {"session_meta", "turn_context"}:
            current_cwd = payload.get("cwd") or current_cwd
        if not in_scope(timestamp, since):
            continue

        if record_type == "response_item" and payload_type in {
            "function_call",
            "custom_tool_call",
            "tool_search_call",
            "web_search_call",
        }:
            tool = str(payload.get("name") or payload_type or "unknown")
            arguments = parse_json_object(payload.get("arguments"))
            if not arguments and payload_type == "custom_tool_call":
                arguments = {"input": payload.get("input")}
            if not arguments and isinstance(payload.get("action"), dict):
                arguments = payload["action"]
            if not arguments and isinstance(payload.get("execution"), dict):
                arguments = payload["execution"]
            call_id = str(payload.get("call_id") or "")
            cwd_text = arguments.get("workdir") or arguments.get("cwd") or current_cwd
            project, cwd = make_project(cwd_text, home)
            if not project_matches(cwd, project_filters):
                continue

            command = arguments.get("cmd") or arguments.get("command")
            is_shell = tool in SHELL_TOOLS or tool.endswith(".exec_command")
            if is_shell and isinstance(command, str):
                normalized = normalize_shell(command, cwd, home)
                event = make_event(
                    source, line, timestamp, tool, project, call_id, normalized, category="shell"
                )
            elif include_experimental:
                targets, features = summarize_tool_input(tool, arguments, cwd, home)
                event = OperationEvent(
                    event_id=event_id(source.source_id, line, call_id),
                    product="codex",
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

        if record_type == "response_item" and payload_type in {
            "function_call_output",
            "custom_tool_call_output",
            "tool_search_output",
        }:
            call_id = str(payload.get("call_id") or "")
            if call_id in by_call_id:
                by_call_id[call_id].outcome = infer_outcome(payload.get("output"))

        if record_type == "event_msg" and payload_type == "web_search_end":
            call_id = str(payload.get("call_id") or "")
            if call_id in by_call_id:
                by_call_id[call_id].outcome = "executed-without-observed-decision"

    return events


def make_event(source, line, timestamp, tool, project, call_id, normalized, category):
    return OperationEvent(
        event_id=event_id(source.source_id, line, call_id),
        product="codex",
        timestamp=iso_timestamp(timestamp),
        category=category,
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


def infer_outcome(output: Any) -> str:
    text = str(output).lower()
    if any(marker in text for marker in ("permission denied", "user denied", "rejected by user")):
        return "denied"
    return "executed-without-observed-decision"


def event_id(source_id: str, line: int, call_id: str) -> str:
    value = f"{source_id}:{line}:{call_id}"
    return "event_" + hashlib.sha256(value.encode()).hexdigest()[:16]
