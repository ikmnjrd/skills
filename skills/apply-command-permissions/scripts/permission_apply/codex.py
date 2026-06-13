from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import PlanError, RuleChange

@dataclass
class ParsedRule:
    pattern: list[str]
    decision: str
    path: Path
    line: int
    end_line: int


def rules_dir(home: Path) -> Path:
    return home / "rules"


def parse_all(home: Path) -> tuple[list[ParsedRule], dict[Path, list[str]]]:
    contents: dict[Path, list[str]] = {}
    parsed: list[ParsedRule] = []
    directory = rules_dir(home)
    for path in sorted(directory.glob("*.rules")) if directory.exists() else []:
        if path.is_symlink():
            raise PlanError(f"Codex rule files must not be symlinks: {path}")
        if path.stat().st_uid != os.getuid():
            raise PlanError(f"Codex rule files must be owned by the current user: {path}")
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        contents[path] = lines
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as error:
            raise PlanError(f"unsupported Codex rule syntax in {path}: {error}") from error
        for node in tree.body:
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "prefix_rule"
            ):
                continue
            keywords = {item.arg: item.value for item in node.value.keywords if item.arg}
            if "pattern" not in keywords or "decision" not in keywords:
                raise PlanError(f"invalid Codex prefix_rule at {path}:{node.lineno}")
            try:
                pattern = ast.literal_eval(keywords["pattern"])
                decision = ast.literal_eval(keywords["decision"])
            except (ValueError, TypeError) as error:
                raise PlanError(f"dynamic Codex prefix_rule at {path}:{node.lineno}") from error
            if not isinstance(pattern, list) or not all(isinstance(item, str) for item in pattern):
                raise PlanError(f"invalid Codex pattern at {path}:{node.lineno}")
            if decision not in {"allow", "prompt", "forbidden"}:
                raise PlanError(f"invalid Codex decision at {path}:{node.lineno}")
            parsed.append(
                ParsedRule(
                    pattern,
                    decision,
                    path,
                    node.lineno,
                    node.end_lineno or node.lineno,
                )
            )
    return parsed, contents


def render_rule(pattern: list[str], decision: str) -> str:
    return f"prefix_rule(pattern={json.dumps(pattern)}, decision={json.dumps(decision)})\n"


def apply_changes(home: Path, changes: list[RuleChange]) -> tuple[dict[Path, bytes], list[dict], list[str]]:
    parsed, contents = parse_all(home)
    target = rules_dir(home) / "default.rules"
    if target not in contents:
        contents[target] = []
    operations = []
    warnings = []

    for change in changes:
        if change.scope != "user":
            raise PlanError("Codex supports user scope only")
        if change.action in {"add", "replace"} and change.decision == "allow" and not change.global_effect_confirmed:
            raise PlanError(f"{change.rule_id}: Codex allow requires global_effect_confirmed=true")
        existing = find_exact(parsed, change.pattern, change.decision)
        if change.action == "add":
            if len(existing) > 1:
                raise PlanError(f"{change.rule_id}: exact Codex rule exists more than once")
            if existing:
                operations.append({"id": change.rule_id, "action": "no-op", "reason": "exact rule exists"})
                continue
            conflict = conflicting_prefix(parsed, change.pattern, change.decision)
            if conflict:
                raise PlanError(f"Codex conflict for {change.rule_id}: {conflict}")
            append_rule(contents[target], render_rule(change.pattern, change.decision))
            parsed.append(
                ParsedRule(
                    change.pattern,
                    change.decision,
                    target,
                    len(contents[target]),
                    len(contents[target]),
                )
            )
            operations.append({"id": change.rule_id, "action": "add", "file": str(target)})
        else:
            old = change.old_rule or {}
            matches = find_exact(parsed, old.get("pattern"), old.get("decision"))
            if len(matches) != 1:
                raise PlanError(f"{change.rule_id}: old_rule must match exactly one Codex rule")
            remove_rule(matches[0], contents)
            parsed.remove(matches[0])
            operations.append({"id": change.rule_id, "action": "remove", "file": str(matches[0].path)})
            if change.action == "replace":
                append_rule(
                    contents[matches[0].path],
                    render_rule(change.pattern, change.decision),
                )
                parsed.append(
                    ParsedRule(
                        change.pattern,
                        change.decision,
                        matches[0].path,
                        len(contents[matches[0].path]),
                        len(contents[matches[0].path]),
                    )
                )
                operations[-1]["action"] = "replace"
    return {path: "".join(lines).encode() for path, lines in contents.items()}, operations, warnings


def find_exact(rules: list[ParsedRule], pattern, decision) -> list[ParsedRule]:
    return [rule for rule in rules if rule.pattern == pattern and rule.decision == decision]


def remove_rule(rule: ParsedRule, contents: dict[Path, list[str]]) -> None:
    for index in range(rule.line - 1, rule.end_line):
        contents[rule.path][index] = ""


def append_rule(lines: list[str], rule: str) -> None:
    if lines and lines[-1] and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(rule)


def conflicting_prefix(rules: list[ParsedRule], pattern: list[str], decision: str) -> str | None:
    for rule in rules:
        related = is_prefix(rule.pattern, pattern) or is_prefix(pattern, rule.pattern)
        if related and rule.decision != decision:
            return f"{rule.decision} {rule.pattern} in {rule.path}:{rule.line}"
    return None


def is_prefix(left: list[str], right: list[str]) -> bool:
    return len(left) <= len(right) and right[: len(left)] == left


def validate_with_codex(files: dict[Path, bytes], changes: list[RuleChange]) -> list[dict]:
    executable = shutil.which("codex")
    if not executable:
        raise PlanError("Codex executable is required for official execpolicy validation")
    with tempfile.TemporaryDirectory() as directory:
        paths = []
        for index, (path, data) in enumerate(sorted(files.items(), key=lambda item: str(item[0]))):
            temp = Path(directory) / f"{index}-{path.name}"
            temp.write_bytes(data)
            paths.append(temp)
        results = []
        for change in changes:
            candidate = Path(directory) / f"candidate-{change.rule_id}.rules"
            candidate.write_text(render_rule(change.pattern, change.decision), encoding="utf-8")
            for command, expected in [
                *((item, change.decision) for item in change.match),
                *((item, None) for item in change.not_match),
            ]:
                if not isinstance(command, list) or not command:
                    raise PlanError(f"{change.rule_id}: Codex test cases must be token arrays")
                actual = execpolicy(executable, [candidate], command)
                if expected is None and actual is not None:
                    raise PlanError(f"{change.rule_id}: not_match unexpectedly matched {command}")
                if expected is not None and actual != expected:
                    raise PlanError(f"{change.rule_id}: expected {expected}, got {actual} for {command}")
                results.append({"id": change.rule_id, "command": command, "decision": actual})
        if paths:
            execpolicy(executable, paths, ["__permission_apply_validation__"])
        return results


def execpolicy(executable: str, rules: list[Path], command: list[str]) -> str | None:
    invocation = [executable, "execpolicy", "check"]
    for path in rules:
        invocation.extend(["--rules", str(path)])
    invocation.extend(command)
    process = subprocess.run(invocation, capture_output=True, text=True)
    if process.returncode:
        raise PlanError(f"Codex execpolicy validation failed: {process.stderr.strip()}")
    try:
        output = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise PlanError("Codex execpolicy returned invalid JSON") from error
    return output.get("decision")
