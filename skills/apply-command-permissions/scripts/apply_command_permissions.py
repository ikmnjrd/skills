#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from permission_apply.engine import ApplyError, apply_plan, dry_run, rollback, status


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Safely apply reviewed agent permission rules.")
    commands = result.add_subparsers(dest="command", required=True)

    for name in ("dry-run", "apply"):
        sub = commands.add_parser(name)
        sub.add_argument("--plan", type=Path, required=True)
        sub.add_argument("--product", choices=("codex", "claude"), required=True)
        if name == "apply":
            sub.add_argument("--confirmation-id", required=True)

    show = commands.add_parser("status")
    show.add_argument("--product", choices=("codex", "claude"), required=True)

    restore = commands.add_parser("rollback")
    restore.add_argument("--product", choices=("codex", "claude"), required=True)
    restore.add_argument("--operation-id", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "dry-run":
            output = dry_run(args.plan, args.product)
        elif args.command == "apply":
            output = apply_plan(args.plan, args.product, args.confirmation_id)
        elif args.command == "status":
            output = status(args.product)
        else:
            output = rollback(args.product, args.operation_id)
    except (ApplyError, OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
