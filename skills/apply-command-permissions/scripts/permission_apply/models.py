from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .io import canonical_json, read_json, sha256_bytes


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class RuleChange:
    rule_id: str
    product: str
    action: str
    decision: str
    pattern: list[str] | str
    scope: str
    source: str
    observed: bool
    reason: str
    match: list[Any]
    not_match: list[Any]
    old_rule: dict | None
    project_path: str | None
    relation_evidence: list[dict]
    strong_confirmation: dict | None
    requires_strong_confirmation: bool
    global_effect_confirmed: bool


@dataclass(frozen=True)
class Plan:
    path: Path
    plan_id: str
    created_at: str
    rules: list[RuleChange]
    raw: dict


def load_plan(path: Path) -> Plan:
    if path.is_symlink() or not path.is_file():
        raise PlanError("plan must be a regular non-symlink file")
    stat = path.stat()
    if stat.st_uid != os.getuid():
        raise PlanError("plan must be owned by the current user")
    if stat.st_mode & 0o077:
        raise PlanError("plan permissions must not grant group or other access")
    try:
        raw = read_json(path)
    except ValueError as error:
        raise PlanError(str(error)) from error
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise PlanError(f"unsupported schema_version: {raw.get('schema_version')}")
    if not isinstance(raw.get("plan_id"), str) or not raw["plan_id"]:
        raise PlanError("plan_id is required")
    if not isinstance(raw.get("created_at"), str):
        raise PlanError("created_at is required")
    try:
        datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise PlanError("created_at must be an ISO-8601 timestamp") from error
    values = raw.get("rules")
    if not isinstance(values, list) or not values:
        raise PlanError("rules must be a non-empty array")
    rules = [parse_rule(value) for value in values]
    ids = [rule.rule_id for rule in rules]
    if len(ids) != len(set(ids)):
        raise PlanError("rule IDs must be unique")
    return Plan(path=path, plan_id=raw["plan_id"], created_at=raw["created_at"], rules=rules, raw=raw)


def parse_rule(value: Any) -> RuleChange:
    if not isinstance(value, dict):
        raise PlanError("each rule must be an object")
    required = ("id", "product", "action", "decision", "pattern", "scope", "source", "reason")
    missing = [key for key in required if key not in value]
    if missing:
        raise PlanError(f"missing rule fields: {', '.join(missing)}")
    if not isinstance(value["id"], str) or not value["id"].startswith("ACP-"):
        raise PlanError("rule id must start with ACP-")
    product = value["product"]
    if product not in {"codex", "claude"}:
        raise PlanError(f"invalid product: {product}")
    action = value["action"]
    if action not in {"add", "remove", "replace"}:
        raise PlanError(f"invalid action: {action}")
    allowed_decisions = {"codex": {"allow", "prompt", "forbidden"}, "claude": {"allow", "ask", "deny"}}
    if value["decision"] not in allowed_decisions[product]:
        raise PlanError(f"invalid {product} decision: {value['decision']}")
    pattern = value["pattern"]
    if product == "codex" and (
        not isinstance(pattern, list)
        or not pattern
        or not all(isinstance(item, str) and item for item in pattern)
    ):
        raise PlanError("Codex pattern must be a non-empty string array")
    if product == "claude" and (not isinstance(pattern, str) or not pattern):
        raise PlanError("Claude pattern must be a non-empty string")
    source = value["source"]
    observed = bool(value.get("observed", False))
    introduces_rule = action in {"add", "replace"}
    if introduces_rule and value["decision"] == "allow" and source != "audit-candidate":
        raise PlanError("unobserved or user-policy allow rules are not permitted")
    if introduces_rule and value["decision"] == "allow" and not observed:
        raise PlanError("allow rules require observed=true")
    if action in {"remove", "replace"} and not isinstance(value.get("old_rule"), dict):
        raise PlanError(f"{action} requires old_rule")
    if action in {"remove", "replace"}:
        old = value["old_rule"]
        if old.get("decision") not in allowed_decisions[product]:
            raise PlanError(f"{action} old_rule has an invalid decision")
        expected_type = list if product == "codex" else str
        if not isinstance(old.get("pattern"), expected_type):
            raise PlanError(f"{action} old_rule has an invalid pattern")
    match = value.get("match")
    not_match = value.get("not_match")
    if not isinstance(match, list) or not match:
        raise PlanError("each rule requires at least one match case")
    if not isinstance(not_match, list) or len(not_match) < 2:
        raise PlanError("each rule requires at least two not_match cases")
    evidence = value.get("relation_evidence", [])
    if not isinstance(evidence, list):
        raise PlanError("relation_evidence must be an array")
    for item in evidence:
        validate_evidence_record(item)
        if item.get("relation") == "unresolved":
            raise PlanError("unresolved relation evidence blocks application")
    return RuleChange(
        rule_id=str(value["id"]),
        product=product,
        action=action,
        decision=value["decision"],
        pattern=pattern,
        scope=value["scope"],
        source=source,
        observed=observed,
        reason=str(value["reason"]),
        match=match,
        not_match=not_match,
        old_rule=value.get("old_rule"),
        project_path=value.get("project_path"),
        relation_evidence=evidence,
        strong_confirmation=value.get("strong_confirmation"),
        requires_strong_confirmation=bool(value.get("requires_strong_confirmation", False)),
        global_effect_confirmed=bool(value.get("global_effect_confirmed", False)),
    )


def validate_evidence_record(value: Any) -> None:
    if not isinstance(value, dict):
        raise PlanError("relation evidence must be an object")
    relation = value.get("relation")
    if relation not in {"equivalent", "subset", "overlap", "disjoint", "unresolved"}:
        raise PlanError(f"invalid relation: {relation}")
    evaluator = value.get("evaluator")
    cases = value.get("cases")
    test_code_hash = value.get("test_code_hash")
    result_hash = value.get("result_hash")
    if not isinstance(evaluator, str) or not evaluator:
        raise PlanError("relation evidence requires evaluator")
    if not isinstance(cases, list) or not cases:
        raise PlanError("relation evidence requires cases")
    if relation == "subset":
        if value.get("subset") not in {"existing", "proposed"}:
            raise PlanError("subset evidence requires subset=existing|proposed")
        if value.get("superset") not in {"existing", "proposed"}:
            raise PlanError("subset evidence requires superset=existing|proposed")
        if value["subset"] == value["superset"]:
            raise PlanError("subset and superset must differ")
    if relation == "disjoint" and (
        not isinstance(value.get("proof"), str) or not value["proof"].strip()
    ):
        raise PlanError("disjoint evidence requires a grammar proof")
    if not isinstance(test_code_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", test_code_hash):
        raise PlanError("relation evidence requires a lowercase SHA-256 test_code_hash")
    expected = sha256_bytes(canonical_json(evidence_result_payload(value)))
    if result_hash != expected:
        raise PlanError("relation evidence result_hash mismatch")


def evidence_result_payload(value: dict) -> dict:
    return {
        key: value[key]
        for key in ("relation", "evaluator", "cases", "subset", "superset", "proof")
        if key in value
    }
