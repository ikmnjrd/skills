from __future__ import annotations

import json
import os
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .io import atomic_write

LIMIT = 100


def root() -> Path:
    return Path.home() / "workspace" / "apply-command-permissions-log"


def product_dir(product: str) -> Path:
    path = root() / product
    for child in (path, path / "backups", path / "plans", path / "test-evidence"):
        child.mkdir(parents=True, exist_ok=True, mode=0o700)
        if child.is_symlink() or not child.is_dir():
            raise ValueError(f"history path must be a real directory: {child}")
        if child.stat().st_uid != os.getuid():
            raise ValueError(f"history path must be owned by the current user: {child}")
        os.chmod(child, 0o700)
    return path


def backup_file(product: str, source: Path, operation_id: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_id = hashlib.sha256(str(source).encode()).hexdigest()[:8]
    name = (
        f".apply-command-permissions-backup-{stamp}-{operation_id}-"
        f"{source_id}-{source.name}"
    )
    destination = product_dir(product) / "backups" / name
    if source.exists():
        shutil.copyfile(source, destination)
    else:
        destination.write_bytes(b"")
    os.chmod(destination, 0o600)
    return destination


def append_log(product: str, record: dict) -> list[str]:
    directory = product_dir(product)
    path = directory / "apply-log.jsonl"
    records = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid application log {path}: {error}") from error
            if isinstance(value, dict):
                records.append(value)
    records.append(record)
    records = records[-LIMIT:]
    content = "".join(json.dumps(item, sort_keys=True) + "\n" for item in records)
    atomic_write(path, content.encode())
    warnings = []
    try:
        prune_artifacts(product, records)
    except OSError as error:
        warnings.append(f"artifact pruning failed: {error}")
    return warnings


def records(product: str) -> list[dict]:
    path = product_dir(product) / "apply-log.jsonl"
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if isinstance(value, dict):
            result.append(value)
    return result


def save_artifact(product: str, category: str, name: str, value: dict) -> Path:
    path = product_dir(product) / category / name
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    return path


def prune_artifacts(product: str, live_records: list[dict]) -> None:
    keep = set()
    for record in live_records:
        for key in ("backup_paths", "plan_path", "evidence_path"):
            value = record.get(key)
            if isinstance(value, list):
                keep.update(value)
            elif isinstance(value, str):
                keep.add(value)
    directory = product_dir(product)
    for category in ("backups", "plans", "test-evidence"):
        files = sorted(
            (directory / category).iterdir(),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files[LIMIT:]:
            if str(path) not in keep:
                path.unlink()
