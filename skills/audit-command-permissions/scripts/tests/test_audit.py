from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from permission_audit.audit import AuditOptions, run_audit
from permission_audit.normalize import normalize_shell
from permission_audit.redact import redact_text


class PermissionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        self.options = AuditOptions(
            codex_home=fixtures / "codex",
            claude_home=fixtures / "claude",
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
            project_filters=[],
            include_experimental=True,
        )

    def test_extracts_shell_and_experimental_events(self) -> None:
        data = run_audit(self.options)
        self.assertEqual(data["schema_version"], "1.0")
        self.assertEqual(data["summary"]["shell_events"], 5)
        self.assertEqual(data["summary"]["experimental_events"], 3)
        self.assertEqual(data["summary"]["outcomes"]["denied"], 1)
        self.assertTrue(data["cross_project_groups"])
        self.assertNotIn("top-secret-value", json.dumps(data))
        self.assertNotIn("api_key=secret", json.dumps(data))
        patch = next(event for event in data["events"] if event["tool"] == "apply_patch")
        self.assertEqual(patch["targets"], ["a.txt"])
        web_search = next(
            event for event in data["events"] if event["tool"] == "web_search_call"
        )
        self.assertEqual(web_search["outcome"], "executed-without-observed-decision")

    def test_feature_tags_are_observations(self) -> None:
        data = run_audit(self.options)
        root_rm = next(
            event
            for event in data["events"]
            if event.get("command") == "rm -rf /"
        )
        self.assertIn("recursive_delete", root_rm["features"])
        self.assertIn("outside_project_path", root_rm["features"])
        self.assertEqual(root_rm["targets"], ["<FILESYSTEM_ROOT>"])
        self.assertNotIn("classification", root_rm)
        git_status = next(
            event for event in data["events"] if event.get("command") == "git status"
        )
        self.assertNotIn("network_access", git_status.get("features", []))
        npm_test = next(
            event for event in data["events"] if event.get("command") == "npm test"
        )
        self.assertNotIn("network_access", npm_test.get("features", []))

    def test_project_paths_are_relative_and_secrets_are_hidden(self) -> None:
        normalized = normalize_shell(
            "rm -rf ./build ~/.ssh/id_ed25519",
            Path("/workspace/sample-project"),
            Path("/home/tester"),
        )
        self.assertIn("build", normalized["targets"])
        self.assertIn("<SECRET_PATH>", normalized["targets"])

    def test_redacts_auth_and_url_query(self) -> None:
        value = redact_text(
            "OPENAI_API_KEY=env-secret curl -H 'Authorization: Bearer abc123' "
            "--token flag-secret https://user:pass@example.test/a?token=abc",
            Path("/home/tester"),
        )
        self.assertNotIn("abc123", value)
        self.assertNotIn("token=abc", value)
        self.assertNotIn("env-secret", value)
        self.assertNotIn("flag-secret", value)
        self.assertNotIn("user:pass", value)
        self.assertIn("<TOKEN>", value)
        self.assertIn("<URL_QUERY>", value)
        self.assertEqual(
            redact_text("https://example.test:invalid/path", Path("/home/tester")),
            "<URL>",
        )

    def test_cli_inspect_rescans_and_filters(self) -> None:
        command = [
            sys.executable,
            str(SCRIPT_DIR / "audit_command_permissions.py"),
            "inspect",
            "--codex-home",
            str(self.options.codex_home),
            "--claude-home",
            str(self.options.claude_home),
            "--since",
            "2026-01-01",
            "--command",
            "rm",
            "--format",
            "json",
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["summary"]["matched_events"], 2)
        self.assertTrue(all(event["executable"] == "rm" for event in data["events"]))
        self.assertEqual(
            {target for event in data["events"] for target in event["targets"]},
            {"build", "<FILESYSTEM_ROOT>"},
        )

    def test_output_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            command = [
                sys.executable,
                str(SCRIPT_DIR / "audit_command_permissions.py"),
                "audit",
                "--codex-home",
                str(self.options.codex_home),
                "--claude-home",
                str(self.options.claude_home),
                "--since",
                "2026-01-01",
                "--output",
                str(output),
            ]
            subprocess.run(command, check=True)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
