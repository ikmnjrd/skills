from __future__ import annotations

import copy
import fnmatch
import json
import os
from pathlib import Path

from .io import canonical_json, sha256_bytes
from .models import PlanError, RuleChange, evidence_result_payload

KEYS = ("allow", "ask", "deny")


def settings_path(claude_home: Path, change: RuleChange) -> Path:
    if change.scope == "user":
        return claude_home / "settings.json"
    if change.scope not in {"project", "project-local"} or not change.project_path:
        raise PlanError("Claude project scopes require project_path")
    filename = "settings.json" if change.scope == "project" else "settings.local.json"
    return Path(change.project_path).expanduser() / ".claude" / filename


def load_settings(path: Path) -> tuple[dict, str, bool]:
    if not path.exists():
        return {}, "  ", True
    if path.is_symlink():
        raise PlanError(f"Claude settings must not be a symlink: {path}")
    if path.stat().st_uid != os.getuid():
        raise PlanError(f"Claude settings must be owned by the current user: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise PlanError(f"invalid Claude settings JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise PlanError(f"Claude settings root must be an object: {path}")
    permissions = value.get("permissions", {})
    if not isinstance(permissions, dict):
        raise PlanError(f"permissions must be an object: {path}")
    for key in KEYS:
        if key in permissions and (
            not isinstance(permissions[key], list)
            or not all(isinstance(item, str) and item for item in permissions[key])
        ):
            raise PlanError(f"permissions.{key} must be a string array: {path}")
    indent = detect_indent(text)
    return value, indent, text.endswith("\n")


def apply_changes(
    claude_home: Path, changes: list[RuleChange]
) -> tuple[dict[Path, bytes], list[dict], list[str]]:
    by_path: dict[Path, list[RuleChange]] = {}
    for change in changes:
        by_path.setdefault(settings_path(claude_home, change), []).append(change)
    outputs = {}
    operations = []
    warnings = ["Claude Code product-native permission validation is unavailable; local validation used."]
    for path, path_changes in by_path.items():
        original, indent, newline = load_settings(path)
        value = copy.deepcopy(original)
        permissions = value.setdefault("permissions", {})
        for change in path_changes:
            bucket = permissions.setdefault(change.decision, [])
            if change.action == "add":
                if bucket.count(change.pattern) > 1:
                    raise PlanError(f"{change.rule_id}: exact Claude rule exists more than once")
                if change.pattern in bucket:
                    operations.append({"id": change.rule_id, "action": "no-op", "file": str(path)})
                    continue
                detect_conflicts(permissions, change)
                bucket.append(change.pattern)
                operations.append({"id": change.rule_id, "action": "add", "file": str(path)})
            else:
                old = change.old_rule or {}
                old_decision = old.get("decision")
                old_pattern = old.get("pattern")
                if (
                    old_decision not in KEYS
                    or not isinstance(permissions.get(old_decision), list)
                    or permissions[old_decision].count(old_pattern) != 1
                ):
                    raise PlanError(f"{change.rule_id}: old_rule must match exactly one Claude rule")
                permissions[old_decision].remove(old_pattern)
                operations.append({"id": change.rule_id, "action": "remove", "file": str(path)})
                if change.action == "replace":
                    detect_conflicts(permissions, change)
                    permissions[change.decision].append(change.pattern)
                    operations[-1]["action"] = "replace"
        validate_unrelated(original, value)
        rendered = json.dumps(value, indent=len(indent), ensure_ascii=False) + ("\n" if newline else "")
        reparsed = json.loads(rendered)
        validate_unrelated(original, reparsed)
        outputs[path] = rendered.encode()
    validate_cases(changes)
    return outputs, operations, warnings


def detect_conflicts(permissions: dict, change: RuleChange) -> None:
    for decision in KEYS:
        for existing in permissions.get(decision, []):
            relation = simple_relation(existing, change.pattern)
            if relation != "disjoint" and decision != change.decision:
                proven_disjoint = any(
                    item.get("existing") == existing
                    and item.get("proposed") == change.pattern
                    and item.get("relation") == "disjoint"
                    for item in change.relation_evidence
                )
                if proven_disjoint:
                    continue
                raise PlanError(
                    f"{change.rule_id}: conflicting {decision} rule overlaps {existing}; "
                    "remove, replace, narrow, or prove disjoint"
                )


def simple_relation(left: str, right: str) -> str:
    if left == right:
        return "equivalent"
    left_prefix = literal_prefix(left)
    right_prefix = literal_prefix(right)
    if not (left_prefix.startswith(right_prefix) or right_prefix.startswith(left_prefix)):
        return "disjoint"
    if left.endswith("*") and right.startswith(left[:-1]):
        return "subset"
    if right.endswith("*") and left.startswith(right[:-1]):
        return "subset"
    if not any(char in left for char in "*?[") and not any(char in right for char in "*?["):
        return "disjoint"
    return "overlap"


def literal_prefix(pattern: str) -> str:
    positions = [pattern.find(char) for char in "*?[" if char in pattern]
    return pattern[: min(positions)] if positions else pattern


def validate_cases(changes: list[RuleChange]) -> list[dict]:
    results = []
    for change in changes:
        for candidate in change.match:
            if not isinstance(candidate, str) or not fnmatch.fnmatchcase(candidate, change.pattern):
                raise PlanError(f"{change.rule_id}: match case failed: {candidate}")
            results.append({"id": change.rule_id, "command": candidate, "matched": True})
        for candidate in change.not_match:
            if not isinstance(candidate, str) or fnmatch.fnmatchcase(candidate, change.pattern):
                raise PlanError(f"{change.rule_id}: not_match case failed: {candidate}")
            results.append({"id": change.rule_id, "command": candidate, "matched": False})
        for evidence in change.relation_evidence:
            validate_evidence(evidence)
    return results


def validate_evidence(evidence: dict) -> None:
    relation = evidence.get("relation")
    if relation not in {"equivalent", "subset", "overlap", "disjoint"}:
        raise PlanError(f"invalid relation evidence: {relation}")
    cases = evidence.get("cases")
    if not isinstance(cases, list) or not cases:
        raise PlanError("relation evidence requires cases")
    existing = evidence.get("existing")
    proposed = evidence.get("proposed")
    evaluator = evidence.get("evaluator")
    test_code_hash = evidence.get("test_code_hash")
    result_hash = evidence.get("result_hash")
    if not isinstance(evaluator, str) or not evaluator:
        raise PlanError("relation evidence requires evaluator")
    if not isinstance(test_code_hash, str) or len(test_code_hash) != 64:
        raise PlanError("relation evidence requires a SHA-256 test_code_hash")
    expected_result_hash = sha256_bytes(canonical_json(evidence_result_payload(evidence)))
    if result_hash != expected_result_hash:
        raise PlanError("relation evidence result_hash mismatch")
    outcomes = set()
    for case in cases:
        command = case.get("command")
        actual = (
            fnmatch.fnmatchcase(command, existing),
            fnmatch.fnmatchcase(command, proposed),
        )
        expected = (case.get("existing"), case.get("proposed"))
        if actual != expected:
            raise PlanError(f"relation evidence case mismatch: {command}")
        outcomes.add(actual)
    if relation == "subset":
        required = (
            {(True, True), (False, True)}
            if evidence.get("subset") == "existing"
            else {(True, True), (True, False)}
        )
    else:
        required = {
            "equivalent": {(True, True)},
            "overlap": {(True, True), (True, False), (False, True)},
            "disjoint": {(True, False), (False, True)},
        }[relation]
    if not required.issubset(outcomes):
        raise PlanError(f"insufficient {relation} evidence cases")


def validate_unrelated(original: dict, proposed: dict) -> None:
    left = {key: value for key, value in original.items() if key != "permissions"}
    right = {key: value for key, value in proposed.items() if key != "permissions"}
    if left != right:
        raise PlanError("Claude settings outside permissions changed")


def detect_indent(text: str) -> str:
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" ")
        if stripped and stripped != line:
            return line[: len(line) - len(stripped)]
    return "  "
