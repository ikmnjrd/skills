from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SCRIPT_DIR))

from permission_apply.engine import ApplyError, apply_plan, dry_run, rollback, status
from permission_apply.history import append_log
from permission_apply.io import canonical_json


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class ApplyPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"HOME": str(self.home), "CODEX_HOME": str(self.home / ".codex")})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def plan(self, rules: list[dict], name: str = "plan.json") -> Path:
        path = self.home / name
        write_json(
            path,
            {
                "schema_version": "1.0",
                "plan_id": "plan-test",
                "created_at": "2026-06-13T00:00:00Z",
                "rules": rules,
            },
        )
        os.chmod(path, 0o600)
        return path

    def test_claude_dry_run_apply_and_rollback_preserves_other_settings(self) -> None:
        settings = self.home / ".claude" / "settings.json"
        write_json(settings, {"permissions": {"allow": ["mcp__pencil"]}, "hooks": {"Stop": []}})
        before = settings.read_bytes()
        plan = self.plan(
            [
                {
                    "id": "ACP-FORBID-001",
                    "product": "claude",
                    "action": "add",
                    "decision": "deny",
                    "pattern": "Bash(git push * --force)",
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Block force pushes",
                    "match": ["Bash(git push origin --force)"],
                    "not_match": ["Bash(git push origin)", "Bash(git status)"],
                }
            ]
        )
        preview = dry_run(plan, "claude")
        self.assertNotIn("hooks", preview["diffs"][str(settings)])
        self.assertEqual(preview["unrelated_settings"], "deep-compared and retained")
        result = apply_plan(plan, "claude", preview["confirmation_id"])
        value = json.loads(settings.read_text())
        self.assertEqual(value["hooks"], {"Stop": []})
        self.assertIn("Bash(git push * --force)", value["permissions"]["deny"])
        self.assertTrue(result["backup_paths"][0].endswith("settings.json"))
        operation_id = result["operation_id"]
        rollback("claude", operation_id)
        self.assertEqual(settings.read_bytes(), before)

    def test_codex_uses_official_execpolicy(self) -> None:
        rules = self.home / ".codex" / "rules" / "default.rules"
        rules.parent.mkdir(parents=True)
        rules.write_text('prefix_rule(pattern=["git", "status"], decision="allow")\n')
        plan = self.plan(
            [
                {
                    "id": "ACP-PROMPT-001",
                    "product": "codex",
                    "action": "add",
                    "decision": "prompt",
                    "pattern": ["git", "push"],
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Review remote writes",
                    "match": [["git", "push", "origin", "main"]],
                    "not_match": [["git", "status"], ["git", "fetch"]],
                }
            ]
        )
        preview = dry_run(plan, "codex")
        result = apply_plan(plan, "codex", preview["confirmation_id"])
        self.assertEqual(result["validation"], "passed")
        self.assertIn('pattern=["git", "push"]', rules.read_text())

    def test_codex_preserves_multiline_rules(self) -> None:
        rules = self.home / ".codex" / "rules" / "default.rules"
        rules.parent.mkdir(parents=True)
        rules.write_text(
            "prefix_rule(\n"
            '    pattern=["git", "status"],\n'
            '    decision="allow",\n'
            '    match=["git status"],\n'
            ")\n",
            encoding="utf-8",
        )
        plan = self.plan(
            [
                {
                    "id": "ACP-PROMPT-MULTILINE",
                    "product": "codex",
                    "action": "add",
                    "decision": "prompt",
                    "pattern": ["git", "push"],
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Preserve existing multiline rule",
                    "match": [["git", "push", "origin", "main"]],
                    "not_match": [["git", "status"], ["git", "fetch"]],
                }
            ]
        )
        preview = dry_run(plan, "codex")
        apply_plan(plan, "codex", preview["confirmation_id"])
        self.assertIn('match=["git status"]', rules.read_text())

    def test_codex_allow_requires_global_confirmation(self) -> None:
        plan = self.plan(
            [
                {
                    "id": "ACP-ALLOW-001",
                    "product": "codex",
                    "action": "add",
                    "decision": "allow",
                    "pattern": ["cargo", "test"],
                    "scope": "user",
                    "source": "audit-candidate",
                    "observed": True,
                    "reason": "Observed tests",
                    "match": [["cargo", "test"]],
                    "not_match": [["cargo", "install"], ["cargo", "publish"]],
                }
            ]
        )
        with self.assertRaises(ApplyError):
            dry_run(plan, "codex")

    def test_relaxation_requires_strong_confirmation(self) -> None:
        settings = self.home / ".claude" / "settings.json"
        write_json(settings, {"permissions": {"deny": ["Bash(rm -rf *)"]}})
        rule = {
            "id": "ACP-REMOVE-001",
            "product": "claude",
            "action": "remove",
            "decision": "deny",
            "pattern": "Bash(rm -rf *)",
            "old_rule": {"decision": "deny", "pattern": "Bash(rm -rf *)"},
            "scope": "user",
            "source": "user-policy",
            "observed": False,
            "reason": "Explicit removal",
            "match": ["Bash(rm -rf build)"],
            "not_match": ["Bash(rm build)", "Bash(ls)"],
        }
        plan = self.plan([rule])
        preview = dry_run(plan, "claude")
        with self.assertRaises(ApplyError):
            apply_plan(plan, "claude", preview["confirmation_id"])

        summary = "Remove deny Bash(rm -rf *); recursive deletion becomes prompt-policy dependent."
        rule["strong_confirmation"] = {
            "confirmed": True,
            "summary": summary,
            "summary_hash": hashlib.sha256(summary.encode()).hexdigest(),
        }
        plan = self.plan([rule], "confirmed.json")
        preview = dry_run(plan, "claude")
        apply_plan(plan, "claude", preview["confirmation_id"])
        self.assertNotIn("Bash(rm -rf *)", json.loads(settings.read_text())["permissions"]["deny"])

    def test_stale_confirmation_is_rejected(self) -> None:
        settings = self.home / ".claude" / "settings.json"
        write_json(settings, {"permissions": {}})
        plan = self.plan(
            [
                {
                    "id": "ACP-ASK-001",
                    "product": "claude",
                    "action": "add",
                    "decision": "ask",
                    "pattern": "Bash(npm install *)",
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Review dependency installs",
                    "match": ["Bash(npm install example)"],
                    "not_match": ["Bash(npm test)", "Bash(npm --version)"],
                }
            ]
        )
        preview = dry_run(plan, "claude")
        write_json(settings, {"permissions": {}, "changed": True})
        with self.assertRaises(ApplyError):
            apply_plan(plan, "claude", preview["confirmation_id"])

    def test_conflicting_claude_decisions_are_rejected(self) -> None:
        settings = self.home / ".claude" / "settings.json"
        write_json(settings, {"permissions": {"allow": ["Bash(git *)"]}})
        plan = self.plan(
            [
                {
                    "id": "ACP-DENY-001",
                    "product": "claude",
                    "action": "add",
                    "decision": "deny",
                    "pattern": "Bash(git push *)",
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Conflicting rule must be resolved",
                    "match": ["Bash(git push origin main)"],
                    "not_match": ["Bash(git status)", "Bash(cargo test)"],
                }
            ]
        )
        with self.assertRaises(ApplyError):
            dry_run(plan, "claude")

    def test_disjoint_relation_evidence_is_reexecuted(self) -> None:
        settings = self.home / ".claude" / "settings.json"
        write_json(settings, {"permissions": {"allow": ["Bash(git [ab]*)"]}})
        cases = [
            {"command": "Bash(git apple)", "existing": True, "proposed": False},
            {"command": "Bash(git cherry)", "existing": False, "proposed": True},
        ]
        payload = {
            "relation": "disjoint",
            "evaluator": "claude-local",
            "cases": cases,
            "proof": "Character classes [ab] and [cd] do not intersect.",
        }
        evidence = {
            "existing": "Bash(git [ab]*)",
            "proposed": "Bash(git [cd]*)",
            **payload,
            "test_code_hash": "0" * 64,
            "result_hash": hashlib.sha256(canonical_json(payload)).hexdigest(),
        }
        plan = self.plan(
            [
                {
                    "id": "ACP-DENY-DISJOINT",
                    "product": "claude",
                    "action": "add",
                    "decision": "deny",
                    "pattern": "Bash(git [cd]*)",
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Verified disjoint pattern",
                    "match": ["Bash(git cherry)"],
                    "not_match": ["Bash(git apple)", "Bash(git status)"],
                    "relation_evidence": [evidence],
                }
            ]
        )
        preview = dry_run(plan, "claude")
        self.assertTrue(preview["ok"])

    def test_history_is_capped_at_100(self) -> None:
        for index in range(101):
            append_log(
                "claude",
                {
                    "operation_id": f"op-{index}",
                    "timestamp": "2026-06-13T00:00:00Z",
                    "backup_paths": [],
                    "original_paths": [],
                },
            )
        result = status("claude")
        self.assertEqual(result["count"], 100)
        self.assertEqual(result["operations"][0]["operation_id"], "op-1")

    def test_plan_must_be_private(self) -> None:
        plan = self.plan(
            [
                {
                    "id": "ACP-ASK-PRIVATE",
                    "product": "claude",
                    "action": "add",
                    "decision": "ask",
                    "pattern": "Bash(npm install *)",
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Private plan test",
                    "match": ["Bash(npm install x)"],
                    "not_match": ["Bash(npm test)", "Bash(ls)"],
                }
            ]
        )
        os.chmod(plan, 0o644)
        with self.assertRaises(ApplyError):
            dry_run(plan, "claude")

    def test_same_named_settings_files_get_distinct_backups(self) -> None:
        project = self.home / "project"
        plan = self.plan(
            [
                {
                    "id": "ACP-ASK-USER",
                    "product": "claude",
                    "action": "add",
                    "decision": "ask",
                    "pattern": "Bash(npm install *)",
                    "scope": "user",
                    "source": "user-policy",
                    "observed": False,
                    "reason": "User scope",
                    "match": ["Bash(npm install x)"],
                    "not_match": ["Bash(npm test)", "Bash(ls)"],
                },
                {
                    "id": "ACP-DENY-PROJECT",
                    "product": "claude",
                    "action": "add",
                    "decision": "deny",
                    "pattern": "Bash(git push * --force)",
                    "scope": "project",
                    "project_path": str(project),
                    "source": "user-policy",
                    "observed": False,
                    "reason": "Project scope",
                    "match": ["Bash(git push origin --force)"],
                    "not_match": ["Bash(git push origin)", "Bash(git status)"],
                },
            ]
        )
        preview = dry_run(plan, "claude")
        result = apply_plan(plan, "claude", preview["confirmation_id"])
        self.assertEqual(len(result["backup_paths"]), 2)
        self.assertEqual(len(set(result["backup_paths"])), 2)


if __name__ == "__main__":
    unittest.main()
