#!/usr/bin/env python3
"""Extract redacted permission-audit facts from Codex and Claude Code logs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from permission_audit.audit import AuditOptions, run_audit
from permission_audit.report import render_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract redacted operation facts; classification remains an LLM task."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="Create canonical audit data or Markdown")
    add_scope_arguments(audit)
    audit.add_argument("--format", choices=("json", "markdown"), default="json")
    audit.add_argument("--output", type=Path)
    audit.add_argument("--output-dir", type=Path)

    inspect = subparsers.add_parser("inspect", help="Re-scan logs and query matching events")
    add_scope_arguments(inspect)
    inspect.add_argument("--command", dest="shell_command", help="Match a shell executable name")
    inspect.add_argument("--tool", help="Match an operation tool name")
    inspect.add_argument("--feature", help="Match an observed feature tag")
    inspect.add_argument("--target", help="Match a redacted target substring")
    inspect.add_argument("--format", choices=("json", "markdown"), default="markdown")
    inspect.add_argument("--output", type=Path)
    return parser


def add_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    parser.add_argument("--since", help="Inclusive ISO date or timestamp; defaults to 90 days ago")
    parser.add_argument("--all-time", action="store_true")
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument(
        "--shell-only",
        action="store_true",
        help="Exclude experimental non-shell operations",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = AuditOptions.from_args(args)
    data = run_audit(options)

    if args.command == "inspect":
        data = filter_events(
            data,
            shell_command=args.shell_command,
            tool=args.tool,
            feature=args.feature,
            target=args.target,
        )

    rendered = (
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        if args.format == "json"
        else render_markdown(data)
    )

    if getattr(args, "output_dir", None):
        write_output(args.output_dir / "audit.json", json.dumps(data, indent=2, sort_keys=True) + "\n")
        write_output(args.output_dir / "audit.md", render_markdown(data))
    elif getattr(args, "output", None):
        write_output(args.output, rendered)
    else:
        sys.stdout.write(rendered)
    return 0


def filter_events(
    data: dict,
    *,
    shell_command: str | None = None,
    tool: str | None,
    feature: str | None,
    target: str | None,
) -> dict:
    executable = shell_command
    matches = []
    for event in data["events"]:
        if executable and event.get("executable") != executable:
            continue
        if tool and event.get("tool") != tool:
            continue
        if feature and feature not in event.get("features", []):
            continue
        if target and not any(target in value for value in event.get("targets", [])):
            continue
        matches.append(event)

    filtered = dict(data)
    filtered["query"] = {
        "command": executable,
        "tool": tool,
        "feature": feature,
        "target": target,
    }
    filtered["events"] = matches
    filtered["summary"] = dict(data["summary"])
    filtered["summary"]["matched_events"] = len(matches)
    filtered["groups"] = []
    filtered["cross_project_groups"] = []
    return filtered


def write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
