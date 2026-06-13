from __future__ import annotations

import copy
import difflib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .claude import apply_changes as apply_claude_changes
from .claude import load_settings as load_claude_settings
from .codex import apply_changes as apply_codex_changes
from .codex import parse_all as parse_codex_all
from .codex import validate_with_codex
from .history import append_log, backup_file, product_dir, records, save_artifact
from .io import atomic_write, canonical_json, file_hash, sha256_bytes
from .models import PlanError, RuleChange, load_plan


class ApplyError(RuntimeError):
    pass


def dry_run(plan_path: Path, product: str) -> dict:
    try:
        plan = load_plan(plan_path)
        changes = [rule for rule in plan.rules if rule.product == product]
        if not changes:
            raise PlanError(f"plan has no {product} rules")
        files, operations, warnings = proposed_files(product, changes)
        tests = validate(product, files, changes)
        current = {
            str(path): {"hash": file_hash(path), "exists": path.exists()} for path in files
        }
        proposed = {
            str(path): {"hash": sha256_bytes(data), "exists": True} for path, data in files.items()
        }
        changed_files = only_changed(files)
        if not changed_files:
            warnings.append("No settings files would change.")
        confirmation = confirmation_id(plan.raw, product, current, proposed)
        result = {
            "ok": True,
            "mode": "dry-run",
            "product": product,
            "plan_id": plan.plan_id,
            "operations": operations,
            "warnings": warnings,
            "current_hashes": current,
            "proposed_hashes": proposed,
            "tests": tests,
            "strong_confirmation_required": [
                change.rule_id for change in changes if needs_strong_confirmation(change, changes)
            ],
            "diffs": make_diffs(changed_files, product),
            "unrelated_settings": (
                "deep-compared and retained" if product == "claude" else "not applicable"
            ),
            "backup_names": [
                f".apply-command-permissions-backup-TIMESTAMP-OPERATION-{path.name}"
                for path in changed_files
            ],
            "confirmation_id": confirmation,
        }
        return result
    except (OSError, ValueError, PlanError) as error:
        raise ApplyError(str(error)) from error


def apply_plan(plan_path: Path, product: str, supplied_confirmation: str) -> dict:
    try:
        return _apply_plan(plan_path, product, supplied_confirmation)
    except ApplyError:
        raise
    except (OSError, ValueError, PlanError) as error:
        raise ApplyError(str(error)) from error


def _apply_plan(plan_path: Path, product: str, supplied_confirmation: str) -> dict:
    preview = dry_run(plan_path, product)
    if preview["confirmation_id"] != supplied_confirmation:
        raise ApplyError("confirmation_id does not match the current plan and settings")
    plan = load_plan(plan_path)
    changes = [rule for rule in plan.rules if rule.product == product]
    validate_strong_confirmations(changes)
    files, operations, warnings = proposed_files(product, changes)
    validate(product, files, changes)
    changed_files = only_changed(files)
    if not changed_files:
        return {
            "ok": True,
            "mode": "apply",
            "product": product,
            "operations": operations,
            "warnings": warnings + ["No settings files changed."],
            "validation": "passed",
        }
    operation_id = f"op-{uuid.uuid4().hex[:12]}"
    backups = {}
    existed = {path: path.exists() for path in changed_files}
    # Ensure required history storage is writable and structurally valid before settings change.
    product_dir(product)
    records(product)
    before_hashes = {str(path): file_hash(path) for path in changed_files}
    try:
        for path in changed_files:
            backups[path] = backup_file(product, path, operation_id)
        for path, data in changed_files.items():
            atomic_write(path, data)
        post_tests = validate(product, files, changes)
        for path, data in changed_files.items():
            if path.read_bytes() != data:
                raise ApplyError(f"post-write content mismatch: {path}")
    except Exception as error:
        for path, backup in backups.items():
            restore_backup(path, backup, existed[path])
        raise ApplyError(f"application failed and was rolled back: {error}") from error

    after_hashes = {str(path): file_hash(path) for path in changed_files}
    try:
        compact_plan = compact_plan_record(plan.raw, product)
        plan_record_path = save_artifact(product, "plans", f"{operation_id}.json", compact_plan)
        evidence_path = save_artifact(
            product,
            "test-evidence",
            f"{operation_id}.json",
            {"tests": post_tests, "confirmation_id": supplied_confirmation},
        )
        record = {
            "operation_id": operation_id,
            "timestamp": now(),
            "product": product,
            "plan_id": plan.plan_id,
            "operations": operations,
            "before_hashes": before_hashes,
            "after_hashes": after_hashes,
            "confirmation_id": supplied_confirmation,
            "backup_paths": [str(path) for path in backups.values()],
            "original_paths": [str(path) for path in backups],
            "original_existed": {str(path): existed[path] for path in backups},
            "plan_path": str(plan_record_path),
            "evidence_path": str(evidence_path),
            "validation": "passed",
        }
        warnings.extend(append_log(product, record))
    except Exception as error:
        for path, backup in backups.items():
            restore_backup(path, backup, existed[path])
        raise ApplyError(f"history persistence failed and settings were rolled back: {error}") from error
    return {
        "ok": True,
        "mode": "apply",
        "operation_id": operation_id,
        "product": product,
        "operations": operations,
        "warnings": warnings,
        "backup_paths": record["backup_paths"],
        "after_hashes": after_hashes,
        "validation": "passed",
    }


def rollback(product: str, operation_id: str) -> dict:
    matches = [item for item in records(product) if item.get("operation_id") == operation_id]
    if len(matches) != 1:
        raise ApplyError("operation_id not found or ambiguous")
    record = matches[0]
    originals = [Path(path) for path in record["original_paths"]]
    backups = [Path(path) for path in record["backup_paths"]]
    for path in originals:
        if path.is_symlink():
            raise ApplyError(f"refusing to roll back through a symlink: {path}")
        expected = record["after_hashes"].get(str(path))
        if file_hash(path) != expected:
            raise ApplyError(f"later changes detected; create an inverse plan instead: {path}")
    current_existed = {path: path.exists() for path in originals}
    current_backups = [backup_file(product, path, f"rollback-{operation_id}") for path in originals]
    try:
        original_existed = record.get("original_existed", {})
        for path, backup in zip(originals, backups):
            restore_backup(path, backup, bool(original_existed.get(str(path), True)))
        for path in originals:
            if file_hash(path) != record["before_hashes"].get(str(path)):
                raise ApplyError(f"rollback hash mismatch: {path}")
        validate_restored(product, originals)
    except Exception as error:
        for path, backup in zip(originals, current_backups):
            restore_backup(path, backup, current_existed[path])
        raise ApplyError(f"rollback failed and current files were restored: {error}") from error
    rollback_id = f"rollback-{uuid.uuid4().hex[:12]}"
    try:
        append_log(
            product,
            {
                "operation_id": rollback_id,
                "timestamp": now(),
                "product": product,
                "rollback_of": operation_id,
                "before_hashes": record["after_hashes"],
                "after_hashes": {str(path): file_hash(path) for path in originals},
                "backup_paths": [str(path) for path in current_backups],
                "original_paths": [str(path) for path in originals],
                "original_existed": {str(path): current_existed[path] for path in originals},
                "validation": "restored",
            },
        )
    except Exception as error:
        for path, backup in zip(originals, current_backups):
            restore_backup(path, backup, current_existed[path])
        raise ApplyError(f"rollback history failed; pre-rollback state restored: {error}") from error
    return {"ok": True, "operation_id": rollback_id, "rollback_of": operation_id}


def status(product: str) -> dict:
    items = records(product)
    return {
        "ok": True,
        "product": product,
        "log_directory": str(product_dir(product)),
        "count": len(items),
        "operations": items,
    }


def proposed_files(product: str, changes: list[RuleChange]):
    if product == "codex":
        home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return apply_codex_changes(home, changes)
    home = Path.home() / ".claude"
    return apply_claude_changes(home, changes)


def validate(product: str, files: dict[Path, bytes], changes: list[RuleChange]) -> list[dict]:
    if product == "codex":
        return validate_with_codex(files, changes)
    # apply_claude_changes already validates structure and cases.
    for path, data in files.items():
        value = json.loads(data)
        if not isinstance(value, dict):
            raise PlanError(f"invalid proposed Claude settings: {path}")
    return [{"id": change.rule_id, "status": "passed-local"} for change in changes]


def validate_strong_confirmations(changes: list[RuleChange]) -> None:
    for change in changes:
        if not needs_strong_confirmation(change, changes):
            continue
        confirmation = change.strong_confirmation
        if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
            raise PlanError(f"{change.rule_id}: strong confirmation is required")
        summary = confirmation.get("summary")
        expected = confirmation.get("summary_hash")
        if not isinstance(summary, str) or sha256_bytes(summary.encode()) != expected:
            raise PlanError(f"{change.rule_id}: invalid strong confirmation hash")


def confirmation_id(plan: dict, product: str, current: dict, proposed: dict) -> str:
    value = {"plan": plan, "product": product, "current": current, "proposed": proposed}
    return sha256_bytes(canonical_json(value))


def make_diffs(files: dict[Path, bytes], product: str) -> dict[str, str]:
    result = {}
    for path, proposed in files.items():
        if product == "claude":
            original_value = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            )
            proposed_value = json.loads(proposed)
            original = json.dumps(
                original_value.get("permissions", {}),
                indent=2,
                sort_keys=True,
            ).splitlines()
            new = json.dumps(
                proposed_value.get("permissions", {}),
                indent=2,
                sort_keys=True,
            ).splitlines()
            from_name = f"{path}:permissions"
            to_name = f"{path}:permissions (proposed)"
        else:
            original = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            new = proposed.decode().splitlines()
            from_name = str(path)
            to_name = f"{path} (proposed)"
        result[str(path)] = "\n".join(
            difflib.unified_diff(
                original,
                new,
                fromfile=from_name,
                tofile=to_name,
                lineterm="",
            )
        )
    return result


def only_changed(files: dict[Path, bytes]) -> dict[Path, bytes]:
    return {
        path: data
        for path, data in files.items()
        if not path.exists() or path.read_bytes() != data
    }


def is_relaxation(change: RuleChange) -> bool:
    if change.action not in {"remove", "replace"} or not change.old_rule:
        return False
    ranks = {
        "codex": {"allow": 0, "prompt": 1, "forbidden": 2},
        "claude": {"allow": 0, "ask": 1, "deny": 2},
    }[change.product]
    old = change.old_rule.get("decision")
    if old not in ranks:
        return True
    if change.action == "remove":
        return ranks[old] > 0
    return ranks[change.decision] < ranks[old]


def needs_strong_confirmation(change: RuleChange, all_changes: list[RuleChange]) -> bool:
    bulk_removal = sum(item.action in {"remove", "replace"} for item in all_changes) > 1
    return change.requires_strong_confirmation or bulk_removal or is_relaxation(change)


def restore_backup(path: Path, backup: Path, existed: bool = True) -> None:
    data = backup.read_bytes()
    if existed:
        atomic_write(path, data)
    elif path.exists():
        path.unlink()


def compact_plan_record(plan: dict, product: str) -> dict:
    value = copy.deepcopy(plan)
    value["rules"] = [rule for rule in value["rules"] if rule.get("product") == product]
    return value


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_restored(product: str, paths: list[Path]) -> None:
    if product == "claude":
        for path in paths:
            if path.exists():
                load_claude_settings(path)
        return
    if not paths:
        return
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    _, contents = parse_codex_all(home)
    files = {path: "".join(lines).encode() for path, lines in contents.items()}
    validate_with_codex(files, [])
