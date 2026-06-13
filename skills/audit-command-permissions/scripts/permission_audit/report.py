from __future__ import annotations


def render_markdown(data: dict) -> str:
    summary = data["summary"]
    lines = [
        "# Permission Audit Facts",
        "",
        "> This report contains observations and feature tags, not safety classifications.",
        "",
        "## Scope",
        "",
        f"- Schema: `{data['schema_version']}`",
        f"- Since: `{data['scope'].get('since') or 'all time'}`",
        f"- Sources scanned: {summary['sources_scanned']}",
        f"- Events: {summary['total_events']} "
        f"(shell {summary['shell_events']}, experimental {summary['experimental_events']})",
        "",
    ]

    if "query" in data:
        lines.extend(["## Inspect Query", "", f"- Matches: {summary['matched_events']}", ""])
        for event in data["events"]:
            lines.extend(render_event(event))
        if not data["events"]:
            lines.append("No matching events.")
            lines.append("")
    else:
        lines.extend(render_groups(data["groups"], "shell", "Shell Operations"))
        lines.extend(render_groups(data["groups"], "experimental", "Experimental Operations"))
        lines.extend(render_cross_project(data.get("cross_project_groups", [])))

    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in data.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_groups(groups: list[dict], category: str, title: str) -> list[str]:
    selected = [group for group in groups if group["category"] == category]
    lines = [f"## {title}", ""]
    if not selected:
        return lines + ["No events.", ""]
    lines.extend(
        [
            "| Project | Tool/shape | Observed | Outcomes | Features |",
            "|---|---|---:|---|---|",
        ]
    )
    for group in selected:
        shape = group.get("normalized_shape") or group["tool"]
        outcomes = ", ".join(f"{key}: {value}" for key, value in group["outcomes"].items())
        features = ", ".join(group["features"]) or "-"
        lines.append(
            f"| {escape(group['project']['name'])} | `{escape(shape)}` | "
            f"{group['observed']} | {escape(outcomes)} | {escape(features)} |"
        )
    lines.append("")
    return lines


def render_event(event: dict) -> list[str]:
    lines = [
        f"### `{event['event_id']}`",
        "",
        f"- Product/tool: `{event['product']}` / `{event['tool']}`",
        f"- Support: `{event['support_level']}`",
        f"- Project: `{event['project']['name']}` (`{event['project']['project_id']}`)",
        f"- Timestamp: `{event.get('timestamp', 'unknown')}`",
        f"- Outcome: `{event['outcome']}`",
        f"- Source: `{event['source']['source_id']}:{event['source']['line']}`",
    ]
    if event.get("command"):
        lines.append(f"- Command: `{escape(event['command'])}`")
    if event.get("targets"):
        lines.append("- Targets: " + ", ".join(f"`{escape(item)}`" for item in event["targets"]))
    if event.get("features"):
        lines.append("- Features: " + ", ".join(f"`{item}`" for item in event["features"]))
    if event.get("limitations"):
        lines.append("- Limitations: " + ", ".join(event["limitations"]))
    lines.append("")
    return lines


def render_cross_project(groups: list[dict]) -> list[str]:
    lines = ["## Cross-Project Trends", ""]
    if not groups:
        return lines + ["No events.", ""]
    lines.extend(
        [
            "| Category | Tool/shape | Observed | Projects | Features |",
            "|---|---|---:|---:|---|",
        ]
    )
    for group in groups:
        shape = group.get("normalized_shape") or group["tool"]
        features = ", ".join(group["features"]) or "-"
        lines.append(
            f"| {group['category']} | `{escape(shape)}` | {group['observed']} | "
            f"{group['project_count']} | {escape(features)} |"
        )
    lines.append("")
    return lines


def escape(value: str) -> str:
    return value.replace("|", "\\|").replace("`", "\\`").replace("\n", " ")
