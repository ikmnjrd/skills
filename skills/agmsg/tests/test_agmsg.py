"""Unit + integration tests for the agmsg Python CLI.

Run from the skill dir:  python3 -m unittest discover -s tests
OS-specific spawn paths are covered with mocks (no real terminals launched).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from agmsg_cli import codex, commands, config, delivery, identity, locking, spawn, storage  # noqa: E402
from agmsg_cli import platform as plat  # noqa: E402
from agmsg_cli.envelope import AgmsgError  # noqa: E402
import agmsg  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.runtime = Path(self.tmp) / ".agmsg"
        for sub in ("db", "teams", "run"):
            (self.runtime / sub).mkdir(parents=True)
        self.project = str(Path(self.tmp) / "project")
        os.makedirs(self.project)
        self._prev = os.environ.get("AGMSG_RUNTIME_DIR")
        os.environ["AGMSG_RUNTIME_DIR"] = str(self.runtime)
        storage.init_db()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("AGMSG_RUNTIME_DIR", None)
        else:
            os.environ["AGMSG_RUNTIME_DIR"] = self._prev
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class TestIdentity(Base):
    def test_join_and_whoami(self):
        identity.join("alpha", "alice", "codex", self.project)
        info = identity.whoami(self.project, "codex")
        self.assertEqual(info["data"]["status"], "agent")
        self.assertEqual(info["data"]["agent"], "alice")
        self.assertEqual(info["data"]["teams"], ["alpha"])
        self.assertTrue(
            info["human"].startswith("agent=alice teams=alpha type=codex ")
        )

    def test_join_idempotent(self):
        identity.join("alpha", "alice", "codex", self.project)
        identity.join("alpha", "alice", "codex", self.project)
        cfg = json.loads(
            (self.runtime / "teams" / "alpha" / "config.json").read_text()
        )
        self.assertEqual(len(cfg["agents"]["alice"]["registrations"]), 1)

    def test_whoami_not_joined(self):
        info = identity.whoami(self.project, "codex")
        self.assertEqual(info["human"], "not_joined=true available_teams=none")

    def test_whoami_suggest(self):
        identity.join("alpha", "alice", "codex", "/other/project")
        info = identity.whoami(self.project, "codex")
        self.assertEqual(info["data"]["status"], "suggest")
        self.assertIn("alice", info["data"]["agents"])

    def test_whoami_multiple(self):
        identity.join("alpha", "alice", "codex", self.project)
        identity.join("alpha", "bob", "codex", self.project)
        info = identity.whoami(self.project, "codex")
        self.assertEqual(info["data"]["status"], "multiple")

    def test_bad_agent_type(self):
        with self.assertRaises(AgmsgError):
            identity.join("alpha", "alice", "gemini", self.project)

    def test_leave_removes_empty_team(self):
        identity.join("alpha", "alice", "codex", self.project)
        res = identity.leave("alpha", "alice")
        self.assertTrue(res["data"]["team_removed"])
        self.assertFalse((self.runtime / "teams" / "alpha").exists())

    def test_leave_unknown(self):
        identity.join("alpha", "alice", "codex", self.project)
        with self.assertRaises(AgmsgError):
            identity.leave("alpha", "ghost")

    def test_rename(self):
        identity.join("alpha", "alice", "codex", self.project)
        storage.send("alpha", "alice", "bob", "hi")
        identity.rename("alpha", "alice", "carol")
        cfg = json.loads(
            (self.runtime / "teams" / "alpha" / "config.json").read_text()
        )
        self.assertIn("carol", cfg["agents"])
        self.assertNotIn("alice", cfg["agents"])
        rows = storage.history("alpha", "carol", 10)
        self.assertEqual(rows[0]["from_agent"], "carol")

    def test_rename_team(self):
        identity.join("alpha", "alice", "codex", self.project)
        storage.send("alpha", "alice", "bob", "hi")
        identity.rename_team("alpha", "beta")
        self.assertTrue((self.runtime / "teams" / "beta").exists())
        self.assertFalse((self.runtime / "teams" / "alpha").exists())
        self.assertEqual(len(storage.history("beta", None, 10)), 1)

    def test_reset(self):
        identity.join("alpha", "alice", "codex", self.project)
        res = identity.reset(self.project, "codex", "alice")
        self.assertEqual(res["data"]["removed"], 1)

    def test_team_info(self):
        identity.join("alpha", "alice", "codex", self.project)
        res = identity.team_info("alpha")
        self.assertIn("1 member(s)", res["human"])
        self.assertIn("alice (codex)", res["human"])


class TestStorage(Base):
    def test_send_inbox_markread(self):
        storage.send("alpha", "alice", "bob", "hello\tworld\nline2")
        rows = storage.unread("alpha", "bob")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["body"], "hello\tworld\nline2")
        storage.mark_read("alpha", "bob")
        self.assertEqual(len(storage.unread("alpha", "bob")), 0)

    def test_history_order_and_status(self):
        storage.send("alpha", "a", "b", "one")
        storage.send("alpha", "b", "a", "two")
        rows = storage.history("alpha", None, 10)
        self.assertEqual([r["body"] for r in rows], ["one", "two"])

    def test_watch_poll(self):
        pairs = [("alpha", "bob")]
        base = storage.max_id(pairs)
        storage.send("alpha", "alice", "bob", "new one")
        new = storage.poll(base, pairs)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["to_agent"], "bob")


class TestLocking(Base):
    def test_claim_state_release(self):
        self.assertEqual(locking.state("alpha", "bob", "s1"), "free")
        self.assertEqual(locking.claim("alpha", "bob", "s1"), "ok")
        self.assertTrue(locking.lock_path("alpha", "bob").exists())
        self.assertEqual(locking.state("alpha", "bob", "s1"), "mine")
        # Same sid re-claims fine.
        self.assertEqual(locking.claim("alpha", "bob", "s1"), "ok")
        locking.release("alpha", "bob", "s1")
        self.assertFalse(locking.lock_path("alpha", "bob").exists())

    def test_held_by_live_session(self):
        # Simulate a live owner via a cc-instance file for our own pid.
        (self.runtime / "run" / f"cc-instance.{os.getpid()}").write_text("live\n")
        locking.claim("alpha", "bob", "live")
        self.assertEqual(locking.claim("alpha", "bob", "other"), "held:live")
        self.assertTrue(locking.state("alpha", "bob", "other").startswith("other:"))

    def test_stale_owner_is_free(self):
        locking.lock_path("alpha", "bob").write_text("deadsid\n")
        # No cc-instance => owner not alive => treated free / reclaimable.
        self.assertEqual(locking.state("alpha", "bob", "x"), "free")
        self.assertEqual(locking.claim("alpha", "bob", "x"), "ok")

    def test_encode_non_ascii(self):
        path = locking.lock_path("チーム", "name/with slash")
        self.assertIn("__", path.name)
        self.assertNotIn("/", path.name.replace(".session", ""))


class TestDelivery(Base):
    def test_claude_monitor_then_status(self):
        delivery.apply("monitor", "claude-code", self.project)
        self.assertEqual(delivery.status_mode("claude-code", self.project), "monitor")
        f = delivery.hooks_file("claude-code", self.project)
        data = json.loads(f.read_text())
        self.assertIn("SessionStart", data["hooks"])
        self.assertIn("SessionEnd", data["hooks"])
        self.assertIn("agmsg.py", data["hooks"]["SessionStart"][0]["hooks"][0]["command"])

    def test_codex_turn(self):
        delivery.apply("turn", "codex", self.project)
        self.assertEqual(delivery.status_mode("codex", self.project), "turn")
        f = delivery.hooks_file("codex", self.project)
        self.assertIn("Stop", json.loads(f.read_text())["hooks"])

    def test_codex_monitor(self):
        delivery.apply("monitor", "codex", self.project)
        self.assertEqual(delivery.status_mode("codex", self.project), "monitor")
        f = delivery.hooks_file("codex", self.project)
        data = json.loads(f.read_text())
        self.assertIn("SessionStart", data["hooks"])
        self.assertIn("SessionEnd", data["hooks"])
        self.assertIn("Stop", data["hooks"])

    def test_codex_monitor_status_reports_degraded_fallback(self):
        identity.join("team", "alice", "codex", self.project)
        delivery.apply("monitor", "codex", self.project)
        previous = os.environ.get("HOME")
        os.environ["HOME"] = str(Path(self.tmp) / "home")
        try:
            status = delivery.do_status("codex", self.project)
        finally:
            if previous is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous
        self.assertIn("bridge processes: 0 alive, 0 stale", status)
        self.assertIn("turn fallback: enabled", status)
        self.assertIn("health: degraded", status)

    def test_codex_monitor_fallback_defers_to_live_bridge(self):
        identity.join("team", "alice", "codex", self.project)
        process = subprocess.Popen(["sleep", "60"])
        pidfile = codex.bridge_path("team", "alice", "pid")
        pidfile.write_text(f"{process.pid}\n")
        try:
            self.assertEqual(
                delivery.check_inbox("codex", self.project),
                ("defer", ""),
            )
        finally:
            process.terminate()
            process.wait()

    def test_codex_monitor_fallback_delivers_without_bridge(self):
        identity.join("team", "alice", "codex", self.project)
        storage.send("team", "bob", "alice", "fallback")
        kind, text = delivery.check_inbox("codex", self.project)
        self.assertEqual(kind, "messages")
        self.assertIn("fallback", text)
        self.assertEqual(storage.unread("team", "alice"), [])

    def test_codex_monitor_set_cleans_stale_bridge_state(self):
        identity.join("team", "alice", "codex", self.project)
        pidfile = codex.bridge_path("team", "alice", "pid")
        metafile = codex.bridge_path("team", "alice", "meta")
        pidfile.write_text("99999999\n")
        metafile.write_text("stale\n")
        previous_home = os.environ.get("HOME")
        previous_path = os.environ.get("PATH")
        os.environ["HOME"] = str(Path(self.tmp) / "home")
        os.environ["PATH"] = ""
        try:
            output = delivery.do_set("monitor", "codex", self.project)
        finally:
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home
            if previous_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous_path
        self.assertIn("Removed 2 stale Codex bridge state file(s).", output)
        self.assertFalse(pidfile.exists())
        self.assertFalse(metafile.exists())

    def test_codex_rejects_both(self):
        with self.assertRaises(AgmsgError):
            delivery.apply("both", "codex", self.project)

    def test_off_strips_entries(self):
        delivery.apply("both", "claude-code", self.project)
        delivery.apply("off", "claude-code", self.project)
        self.assertEqual(delivery.status_mode("claude-code", self.project), "off")

    def test_apply_preserves_foreign_hooks(self):
        f = delivery.hooks_file("claude-code", self.project)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"hooks": {"Stop": [
            {"matcher": "", "hooks": [{"type": "command", "command": "echo other"}]}
        ]}}))
        delivery.apply("turn", "claude-code", self.project)
        stop = json.loads(f.read_text())["hooks"]["Stop"]
        self.assertEqual(len(stop), 2)  # foreign + agmsg

    def test_apply_replaces_legacy_shell_hook(self):
        f = delivery.hooks_file("codex", self.project)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"hooks": {"Stop": [
            {"matcher": "", "hooks": [{"type": "command", "command":
                "/home/test/.codex/skills/agmsg/scripts/check-inbox.sh "
                "codex /tmp/project"}]},
            {"matcher": "", "hooks": [{"type": "command", "command":
                "/usr/local/bin/foreign-hook"}]},
        ]}}))

        delivery.apply("turn", "codex", self.project)

        commands = [
            hook["command"]
            for entry in json.loads(f.read_text())["hooks"]["Stop"]
            for hook in entry["hooks"]
        ]
        self.assertEqual(len(commands), 2)
        self.assertIn("/usr/local/bin/foreign-hook", commands)
        self.assertTrue(any("agmsg.py check-inbox" in cmd for cmd in commands))
        self.assertFalse(any("/agmsg/scripts/" in cmd for cmd in commands))

    def test_check_inbox_marks_read(self):
        identity.join("alpha", "bob", "claude-code", self.project)
        storage.send("alpha", "alice", "bob", "ping")
        kind, text = delivery.check_inbox("claude-code", self.project)
        self.assertEqual(kind, "messages")
        self.assertIn("ping", text)
        self.assertEqual(len(storage.unread("alpha", "bob")), 0)

    def test_check_inbox_cooldown(self):
        identity.join("alpha", "bob", "claude-code", self.project)
        storage.send("alpha", "alice", "bob", "one")
        kind, _ = delivery.check_inbox("claude-code", self.project)
        self.assertEqual(kind, "messages")
        # Second message within the cooldown window is held back.
        storage.send("alpha", "alice", "bob", "two")
        kind, _ = delivery.check_inbox("claude-code", self.project)
        self.assertEqual(kind, "cooldown")
        self.assertEqual(len(storage.unread("alpha", "bob")), 1)
        # With the interval at 0, delivery resumes.
        config.set_value("delivery.turn.check_interval", "0")
        kind, text = delivery.check_inbox("claude-code", self.project)
        self.assertEqual(kind, "messages")
        self.assertIn("two", text)

    def test_check_inbox_defers_to_watcher(self):
        identity.join("alpha", "bob", "claude-code", self.project)
        storage.send("alpha", "alice", "bob", "ping")
        sid = "sess-defer"
        (self.runtime / "run" / f"watch.{sid}.pid").write_text(f"{os.getpid()}\n")
        kind, _ = delivery.check_inbox(
            "claude-code", self.project, json.dumps({"session_id": sid})
        )
        self.assertEqual(kind, "defer")
        self.assertEqual(len(storage.unread("alpha", "bob")), 1)

    def test_apply_rejects_broken_hook_json(self):
        f = delivery.hooks_file("claude-code", self.project)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{not json")
        with self.assertRaises(AgmsgError):
            delivery.apply("turn", "claude-code", self.project)
        # Original file is left untouched.
        self.assertEqual(f.read_text(), "{not json")


class TestSession(Base):
    def test_sid_alive_via_cc_instance(self):
        (self.runtime / "run" / f"cc-instance.{os.getpid()}").write_text("live\n")
        self.assertTrue(locking.sid_alive("live"))
        # A live owner cannot be stolen by another session.
        self.assertEqual(locking.claim("alpha", "bob", "live"), "ok")
        self.assertEqual(locking.claim("alpha", "bob", "thief"), "held:live")

    def test_refire_cleans_previous_watcher(self):
        run = self.runtime / "run"
        (run / f"cc-instance.{os.getpid()}").write_text("old-sid\n")
        (run / "watch.old-sid.pid").write_text("2147483646\n")  # dead pid
        delivery._cc_instance_bookkeeping("new-sid", os.getpid())
        self.assertEqual(
            (run / f"cc-instance.{os.getpid()}").read_text().strip(), "new-sid"
        )
        self.assertFalse((run / "watch.old-sid.pid").exists())

    def test_stale_cc_instance_reaped(self):
        run = self.runtime / "run"
        (run / "cc-instance.2147483646").write_text("ghost\n")  # dead pid
        (run / "watch.ghost.pid").write_text("2147483645\n")
        delivery._cc_instance_bookkeeping("x", None)
        self.assertFalse((run / "cc-instance.2147483646").exists())
        self.assertFalse((run / "watch.ghost.pid").exists())


class TestConfig(Base):
    def test_default_and_get(self):
        self.assertEqual(config.get_int("delivery.monitor.poll_interval", 5), 5)

    def test_set_nested(self):
        config.set_value("delivery.monitor.poll_interval", "9")
        self.assertEqual(config.get_int("delivery.monitor.poll_interval", 5), 9)

    def test_set_creates_path(self):
        config.set_value("a.b.c", "true")
        self.assertEqual(config.get("a.b.c"), True)


class TestSpawn(Base):
    def setUp(self):
        super().setUp()
        identity.join("alpha", "peer", "claude-code", self.project)
        self.launched = []
        spawn._runner = lambda argv, cwd: self.launched.append((argv, cwd))

    def tearDown(self):
        spawn._runner = None
        super().tearDown()

    def _patch(self, which=None, environ=None, os_name="linux"):
        import shutil as _sh

        self._owhich = _sh.which
        self._oenv = dict(os.environ)
        self._oos = plat.os_name
        _sh.which = which or (lambda b: f"/usr/bin/{b}")
        plat.os_name = lambda: os_name
        if environ is not None:
            for k, v in environ.items():
                os.environ[k] = v

    def _unpatch(self):
        import shutil as _sh

        _sh.which = self._owhich
        plat.os_name = self._oos
        os.environ.clear()
        os.environ.update(self._oenv)

    def test_tmux_pane(self):
        self._patch(environ={"TMUX": "/tmp/tmux-sock", "DISPLAY": ":0"})
        try:
            res = spawn.spawn("claude-code", "peer", project=self.project, team="alpha")
        finally:
            self._unpatch()
        self.assertEqual(len(self.launched), 1)
        argv = self.launched[0][0]
        self.assertEqual(argv[0], "tmux")
        self.assertIn("split-window", argv)
        self.assertIn("/agmsg actas peer", argv)
        self.assertIn("tmux", res["data"]["mode"])

    def test_linux_gnome_terminal(self):
        self._patch(environ={"DISPLAY": ":0"})
        os.environ.pop("TMUX", None)
        try:
            spawn.spawn("claude-code", "peer", project=self.project, team="alpha")
        finally:
            self._unpatch()
        argv = self.launched[0][0]
        self.assertEqual(argv[0], "gnome-terminal")
        self.assertIn("claude", argv)

    def test_macos_osascript(self):
        self._patch(environ={}, os_name="macos")
        os.environ.pop("TMUX", None)
        try:
            spawn.spawn("claude-code", "peer", project=self.project, team="alpha")
        finally:
            self._unpatch()
        argv = self.launched[0][0]
        self.assertEqual(argv[0], "osascript")
        self.assertIn("Terminal", argv[2])

    def test_bad_split(self):
        with self.assertRaises(AgmsgError):
            spawn.spawn("claude-code", "peer", project=self.project, team="alpha", split="x")

    def test_claude_prompt_uses_slash(self):
        self._patch(environ={"TMUX": "/tmp/s", "DISPLAY": ":0"})
        try:
            spawn.spawn("claude-code", "peer", project=self.project, team="alpha")
        finally:
            self._unpatch()
        argv = self.launched[0][0]
        self.assertIn("claude", argv)
        self.assertIn("/agmsg actas peer", argv)

    def test_codex_prompt_uses_dollar(self):
        identity.join("alpha", "peer", "codex", self.project)
        self._patch(environ={"TMUX": "/tmp/s", "DISPLAY": ":0"})
        try:
            spawn.spawn("codex", "peer", project=self.project, team="alpha")
        finally:
            self._unpatch()
        argv = self.launched[0][0]
        self.assertIn("codex", argv)
        self.assertIn("$agmsg actas peer", argv)


class TestEnvelopeAndDispatch(Base):
    def test_json_envelope_success(self):
        identity.join("alpha", "alice", "codex", self.project)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agmsg.main(["--json", "whoami", self.project, "codex"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["command"], "whoami")

    def test_json_envelope_error(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agmsg.main(["--json", "team", "ghost"])
        self.assertNotEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "team_not_found")

    def test_unknown_command(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agmsg.main(["bogus"])
        self.assertEqual(rc, 2)

    def test_send_then_inbox_dispatch(self):
        identity.join("alpha", "bob", "claude-code", self.project)
        buf = io.StringIO()
        with redirect_stdout(buf):
            agmsg.main(["send", "alpha", "alice", "bob", "hi there"])
            agmsg.main(["inbox", "alpha", "bob"])
        self.assertIn("hi there", buf.getvalue())

    def test_json_only_global_before_command(self):
        # --json as a leading global flag enables the envelope.
        identity.join("alpha", "alice", "codex", self.project)
        buf = io.StringIO()
        with redirect_stdout(buf):
            agmsg.main(["--json", "whoami", self.project, "codex"])
        self.assertTrue(json.loads(buf.getvalue())["ok"])

    def test_json_in_message_body_preserved(self):
        # A literal "--json" inside command args is NOT consumed as the flag.
        identity.join("alpha", "bob", "claude-code", self.project)
        buf = io.StringIO()
        with redirect_stdout(buf):
            agmsg.main(["send", "alpha", "alice", "bob", "--json"])
        # Human output (not an envelope) and the body is the literal token.
        self.assertNotIn('"schema_version"', buf.getvalue())
        rows = storage.unread("alpha", "bob")
        self.assertEqual(rows[0]["body"], "--json")


class TestActasExclusivity(Base):
    def test_turn_mode_actas_blocks_other_session(self):
        identity.join("alpha", "role", "claude-code", self.project)
        orig = delivery._find_cc_pid
        delivery._find_cc_pid = lambda: os.getpid()  # pretend we are the CC proc
        try:
            os.environ["CLAUDE_CODE_SESSION_ID"] = "s1"
            commands.cmd_actas(
                ["role", "--project", self.project, "--type", "claude-code"], False
            )
        finally:
            delivery._find_cc_pid = orig
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        # s1 is registered (alive) and owns the lock; s2 cannot reclaim it.
        self.assertTrue(locking.sid_alive("s1"))
        self.assertEqual(locking.claim("alpha", "role", "s2"), "held:s1")
        # drop/session-end style cleanup releases the lock.
        identity.reset(self.project, "claude-code", "role", "s1")
        self.assertFalse(locking.lock_path("alpha", "role").exists())


class TestCorruptionGuards(Base):
    def test_team_join_preserves_corrupt_file(self):
        path = self.runtime / "teams" / "alpha" / "config.json"
        path.parent.mkdir(parents=True)
        path.write_text("{bad json")
        with self.assertRaises(AgmsgError):
            identity.join("alpha", "x", "codex", self.project)
        self.assertEqual(path.read_text(), "{bad json")

    def test_config_set_preserves_corrupt_file(self):
        cfg = self.runtime / "config.json"
        cfg.write_text("not json")
        with self.assertRaises(AgmsgError):
            config.set_value("a.b", "1")
        self.assertEqual(cfg.read_text(), "not json")

    def test_config_rejects_non_object_root(self):
        (self.runtime / "config.json").write_text("[]")
        with self.assertRaises(AgmsgError):
            config.load()


class TestHookRobustness(Base):
    def test_apply_rejects_array_root(self):
        f = delivery.hooks_file("claude-code", self.project)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("[]")
        with self.assertRaises(AgmsgError):
            delivery.apply("turn", "claude-code", self.project)
        self.assertEqual(f.read_text(), "[]")

    def test_hook_type_error_renders_json_envelope(self):
        f = delivery.hooks_file("claude-code", self.project)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('"a string"')
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agmsg.main(
                ["--json", "delivery", "set", "turn", "claude-code", self.project]
            )
        self.assertNotEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "hook_type_error")

    def test_atomic_write_failure_preserves_original(self):
        f = delivery.hooks_file("claude-code", self.project)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('{"hooks": {}}')
        orig_replace = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            with self.assertRaises(AgmsgError):
                delivery.apply("turn", "claude-code", self.project)
        finally:
            os.replace = orig_replace
        self.assertEqual(f.read_text(), '{"hooks": {}}')
        leftovers = [p for p in f.parent.iterdir() if p.name.startswith(".tmp.")]
        self.assertEqual(leftovers, [])


class TestAtomicSave(Base):
    def test_config_set_write_failure_envelope(self):
        # config.json is a directory => os.replace fails => clean envelope.
        (self.runtime / "config.json").mkdir()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agmsg.main(["--json", "config", "set", "a.b", "1"])
        self.assertNotEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "config_write_error")

    def test_join_write_failure_envelope(self):
        # teams/alpha/config.json is a directory => join save fails cleanly.
        (self.runtime / "teams" / "alpha" / "config.json").mkdir(parents=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agmsg.main(["--json", "join", "alpha", "x", "codex", self.project])
        self.assertNotEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "team_write_error")
        # No temp leftovers in the team directory.
        leftovers = [
            p
            for p in (self.runtime / "teams" / "alpha").iterdir()
            if p.name.startswith(".tmp.")
        ]
        self.assertEqual(leftovers, [])


class TestCodexMonitor(Base):
    def setUp(self):
        super().setUp()
        self._ambient_codex_bridge_env = {
            key: os.environ.pop(key)
            for key in (
                "AGMSG_CODEX_BRIDGE",
                "AGMSG_CODEX_BRIDGE_APP_SERVER",
                "AGMSG_CODEX_BRIDGE_LAUNCHER",
                "AGMSG_CODEX_DESKTOP_BRIDGE",
                "AGMSG_REAL_CODEX",
            )
            if key in os.environ
        }

    def tearDown(self):
        os.environ.update(self._ambient_codex_bridge_env)
        super().tearDown()

    def _environment(self, **changes):
        previous = dict(os.environ)
        os.environ.update({k: str(v) for k, v in changes.items()})
        return previous

    def _restore_environment(self, previous):
        os.environ.clear()
        os.environ.update(previous)

    def _fake_app_server(self, mode: str) -> tuple[Path, Path]:
        script = Path(self.tmp) / "fake_app_server.py"
        log = Path(self.tmp) / "fake_app_server.log"
        script.write_text(
            textwrap.dedent(
                r"""
                import json
                import sys
                import threading

                mode, log_path = sys.argv[1:3]
                wakes = 0
                turns = 0

                def send(value):
                    sys.stdout.write(json.dumps(value) + "\n")
                    sys.stdout.flush()

                def notify(method, params):
                    send({"jsonrpc": "2.0", "method": method, "params": params})

                for line in sys.stdin:
                    message = json.loads(line)
                    method = message.get("method")
                    with open(log_path, "a", encoding="utf-8") as stream:
                        stream.write(method + "\n")
                    if method == "initialize":
                        send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                    elif method == "thread/start":
                        send({
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {"thread": {"id": "thread-1", "status": {"type": "idle"}}},
                        })
                    elif method == "thread/resume":
                        send({
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {
                                "thread": {
                                    "id": message["params"]["threadId"],
                                    "status": {"type": "active"},
                                }
                            },
                        })
                        threading.Timer(
                            0.08,
                            notify,
                            args=(
                                "thread/status/changed",
                                {
                                    "threadId": message["params"]["threadId"],
                                    "status": {"type": "idle"},
                                },
                            ),
                        ).start()
                    elif method == "process/spawn":
                        wakes += 1
                        send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                        max_id = 7 if mode == "stale" else wakes
                        if mode == "active":
                            max_id = 5 if turns == 0 else 6
                        threading.Timer(
                            0.01,
                            notify,
                            args=(
                                "process/exited",
                                {
                                    "processHandle": message["params"]["processHandle"],
                                    "exitCode": 0,
                                    "stdout": f"status=pending count=1 max_id={max_id}\n",
                                    "stderr": "",
                                },
                            ),
                        ).start()
                    elif method == "turn/start":
                        turns += 1
                        text = message["params"]["input"][0]["text"]
                        if mode == "inline" and "inline body reaches prompt" not in text:
                            send({
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "error": {"message": "missing inline body"},
                            })
                            continue
                        send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                        if mode != "watchdog":
                            threading.Timer(
                                0.01,
                                notify,
                                args=(
                                    "turn/completed",
                                    {"threadId": message["params"]["threadId"]},
                                ),
                            ).start()
                    elif method == "process/kill":
                        send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                """
            ).lstrip(),
            encoding="utf-8",
        )
        return script, log

    def test_watch_once_reports_pending_without_marking_read(self):
        identity.join("team", "alice", "codex", self.project)
        storage.send("team", "bob", "alice", "ping")
        output = io.StringIO()
        with redirect_stdout(output):
            rc = codex.watch_once(
                self.project,
                "codex",
                team="team",
                name="alice",
                timeout=1,
                interval=1,
            )
        self.assertEqual(rc, 0)
        self.assertIn("status=pending count=1", output.getvalue())
        self.assertEqual(len(storage.unread("team", "alice")), 1)

    def test_codex_session_start_publishes_launcher_request(self):
        identity.join("team", "alice", "codex", self.project)
        previous = self._environment(
            AGMSG_CODEX_BRIDGE="1",
            AGMSG_CODEX_BRIDGE_LAUNCHER="1",
            AGMSG_CODEX_BRIDGE_APP_SERVER="unix:///tmp/agmsg-test.sock",
            CODEX_THREAD_ID="thread-123",
        )
        try:
            self.assertEqual(delivery.session_start("codex", self.project), "")
        finally:
            self._restore_environment(previous)
        request = json.loads(codex.request_path(self.project).read_text())
        self.assertEqual(request["team"], "team")
        self.assertEqual(request["name"], "alice")
        self.assertEqual(request["thread"], "thread-123")

    def test_codex_desktop_bridge_starts_for_current_thread(self):
        identity.join("team", "alice", "codex", self.project)
        previous = self._environment(
            CODEX_INTERNAL_ORIGINATOR_OVERRIDE="Codex Desktop",
            CODEX_THREAD_ID="desktop-thread",
            AGMSG_REAL_CODEX="/usr/bin/true",
        )
        try:
            with mock.patch.object(codex.subprocess, "Popen") as popen:
                self.assertTrue(codex.start_desktop_bridge(self.project))
        finally:
            self._restore_environment(previous)
        argv = popen.call_args.args[0]
        self.assertIn("codex-bridge", argv)
        self.assertEqual(argv[argv.index("--thread") + 1], "desktop-thread")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(
            popen.call_args.kwargs["env"]["AGMSG_CODEX_DESKTOP_BRIDGE"], "1"
        )

    def test_codex_desktop_stop_hook_starts_bridge(self):
        identity.join("team", "alice", "codex", self.project)
        delivery.apply("monitor", "codex", self.project)
        with mock.patch.object(
            codex, "start_desktop_bridge", return_value=True
        ) as start:
            self.assertEqual(
                delivery.check_inbox("codex", self.project),
                ("none", ""),
            )
        start.assert_called_once_with(self.project)

    def test_codex_session_end_stops_desktop_bridge_without_session_id(self):
        with mock.patch.object(codex, "stop_bridges", return_value=1) as stop:
            self.assertEqual(delivery.session_end("codex", self.project), "")
        stop.assert_called_once_with(self.project)

    def test_codex_nested_desktop_bridge_session_end_does_not_stop_itself(self):
        previous = self._environment(AGMSG_CODEX_DESKTOP_BRIDGE="1")
        try:
            with mock.patch.object(codex, "stop_bridges") as stop:
                self.assertEqual(delivery.session_end("codex", self.project), "")
        finally:
            self._restore_environment(previous)
        stop.assert_not_called()

    def test_resolve_thread_id_from_rollout(self):
        sessions = Path(self.tmp) / "home" / ".codex" / "sessions" / "2026" / "06" / "18"
        sessions.mkdir(parents=True)
        rollout = sessions / "rollout-test.jsonl"
        rollout.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"id": "rollout-thread", "cwd": self.project},
                }
            )
            + "\n"
        )
        previous = self._environment(HOME=Path(self.tmp) / "home")
        os.environ.pop("CODEX_THREAD_ID", None)
        try:
            self.assertEqual(codex.resolve_thread_id(self.project), "rollout-thread")
        finally:
            self._restore_environment(previous)

    def test_desktop_thread_busy_tracks_started_and_completed_turns(self):
        sessions = Path(self.tmp) / "home" / ".codex" / "sessions" / "2026" / "06" / "19"
        sessions.mkdir(parents=True)
        rollout = sessions / "rollout-test-desktop-thread.jsonl"
        rollout.write_text(
            "\n".join(
                json.dumps(
                    {"type": "event_msg", "payload": {"type": kind}}
                )
                for kind in ("task_started", "task_complete", "task_started")
            )
            + "\n"
        )
        previous = self._environment(HOME=Path(self.tmp) / "home")
        try:
            self.assertTrue(codex.desktop_thread_busy("desktop-thread"))
            with rollout.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {"type": "task_complete"},
                        }
                    )
                    + "\n"
                )
            self.assertFalse(codex.desktop_thread_busy("desktop-thread"))
        finally:
            self._restore_environment(previous)

    def test_shim_routes_only_interactive_monitor_launches(self):
        fake_bin = Path(self.tmp) / "bin"
        fake_bin.mkdir()
        real = fake_bin / "codex"
        real.write_text("#!/bin/sh\nexit 0\n")
        real.chmod(0o755)
        delivery.apply("monitor", "codex", self.project)
        previous = self._environment(
            PATH=str(fake_bin),
            HOME=Path(self.tmp) / "home",
            AGMSG_CODEX_SHIM_TARGET=Path(self.tmp) / "home" / ".agents" / "bin" / "codex",
        )
        try:
            executable, argv, env = codex.shim_invocation(
                ["--cd", self.project, "resume", "--last"]
            )
            self.assertEqual(executable, plat.python_executable())
            self.assertIn("codex-monitor", argv)
            self.assertIn("--last", argv)
            self.assertEqual(env["AGMSG_REAL_CODEX"], str(real.resolve()))

            executable, argv, _ = codex.shim_invocation(
                ["--cd", self.project, "exec", "echo", "hi"]
            )
            self.assertEqual(executable, str(real.resolve()))
            self.assertIn("exec", argv)
            self.assertNotIn("codex-monitor", argv)
        finally:
            self._restore_environment(previous)

    def test_shim_installer_refuses_foreign_command(self):
        previous = self._environment(HOME=Path(self.tmp) / "home")
        try:
            target = codex.shim_target()
            target.parent.mkdir(parents=True)
            target.write_text("#!/bin/sh\necho foreign\n")
            with self.assertRaises(AgmsgError):
                codex.install_shim()
            self.assertIn("foreign", target.read_text())
        finally:
            self._restore_environment(previous)

    def test_shim_path_check_requires_precedence_over_real_codex(self):
        real_dir = Path(self.tmp) / "real-bin"
        real_dir.mkdir()
        real = real_dir / "codex"
        real.write_text("#!/bin/sh\nexit 0\n")
        real.chmod(0o755)
        home = Path(self.tmp) / "home"
        shim_dir = home / ".agents" / "bin"
        previous = self._environment(
            HOME=home,
            PATH=f"{real_dir}{os.pathsep}{shim_dir}",
        )
        try:
            target, on_path = codex.install_shim()
            self.assertFalse(on_path)
            os.environ["PATH"] = f"{shim_dir}{os.pathsep}{real_dir}"
            target, on_path = codex.install_shim()
            self.assertTrue(on_path)
            self.assertEqual(target, shim_dir / "codex")
        finally:
            self._restore_environment(previous)

    def test_generated_shim_passes_non_monitor_commands_to_real_codex(self):
        real_dir = Path(self.tmp) / "real-bin"
        real_dir.mkdir()
        real = real_dir / "codex"
        real.write_text("#!/bin/sh\nprintf 'real:%s\\n' \"$*\"\n")
        real.chmod(0o755)
        home = Path(self.tmp) / "home"
        shim_dir = home / ".agents" / "bin"
        previous = self._environment(
            HOME=home,
            PATH=f"{shim_dir}{os.pathsep}{real_dir}",
        )
        try:
            target, on_path = codex.install_shim()
            self.assertTrue(on_path)
            result = subprocess.run(
                [str(target), "--version"],
                cwd=self.project,
                env=dict(os.environ),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "real:--version")
        finally:
            self._restore_environment(previous)

    def test_switching_codex_monitor_to_turn_stops_bridge(self):
        identity.join("team", "alice", "codex", self.project)
        process = subprocess.Popen(["sleep", "60"])
        pidfile = codex.bridge_path("team", "alice", "pid")
        metafile = codex.bridge_path("team", "alice", "meta")
        logfile = codex.bridge_path("team", "alice", "log")
        pidfile.write_text(f"{process.pid}\n")
        metafile.write_text(f"pid={process.pid}\nproject={self.project}\n")
        logfile.write_text("")
        try:
            delivery.apply("monitor", "codex", self.project)
            delivery.do_set("turn", "codex", self.project)
            process.wait(timeout=2)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        self.assertFalse(pidfile.exists())
        self.assertFalse(metafile.exists())
        self.assertFalse(logfile.exists())

    def test_bridge_rearms_via_watchdog(self):
        identity.join("team", "alice", "codex", self.project)
        script, log = self._fake_app_server("watchdog")
        previous = self._environment(
            AGMSG_CODEX_APP_SERVER_CMD=f"{sys.executable} {script} watchdog {log}"
        )
        try:
            bridge = codex.CodexBridge(
                self.project,
                "team",
                "alice",
                timeout=1,
                interval=1,
                max_wakes=2,
                turn_timeout=0.05,
            )
            self.assertEqual(bridge.run(), 0)
        finally:
            self._restore_environment(previous)
        methods = log.read_text().splitlines()
        self.assertEqual(methods.count("process/spawn"), 2)
        self.assertEqual(methods.count("turn/start"), 2)

    def test_bridge_delivers_wake_after_active_thread_becomes_idle(self):
        identity.join("team", "alice", "codex", self.project)
        script, log = self._fake_app_server("active")
        previous = self._environment(
            AGMSG_CODEX_APP_SERVER_CMD=f"{sys.executable} {script} active {log}"
        )
        try:
            bridge = codex.CodexBridge(
                self.project,
                "team",
                "alice",
                thread_id="thread-active",
                timeout=1,
                interval=1,
                max_wakes=2,
                turn_timeout=1,
            )
            self.assertEqual(bridge.run(), 0)
        finally:
            self._restore_environment(previous)
        methods = log.read_text().splitlines()
        self.assertGreaterEqual(methods.count("turn/start"), 1)
        self.assertEqual(methods.count("process/spawn"), 2)

    def test_bridge_inlines_and_marks_inbox_read(self):
        identity.join("team", "alice", "codex", self.project)
        storage.send("team", "bob", "alice", "inline body reaches prompt")
        script, log = self._fake_app_server("inline")
        previous = self._environment(
            AGMSG_CODEX_APP_SERVER_CMD=f"{sys.executable} {script} inline {log}"
        )
        try:
            bridge = codex.CodexBridge(
                self.project,
                "team",
                "alice",
                timeout=1,
                interval=1,
                max_wakes=1,
                turn_timeout=1,
                inline_inbox=True,
            )
            self.assertEqual(bridge.run(), 0)
        finally:
            self._restore_environment(previous)
        self.assertIn("turn/start", log.read_text())
        self.assertEqual(storage.unread("team", "alice"), [])

    def test_bridge_stops_repeated_stale_wakeup(self):
        identity.join("team", "alice", "codex", self.project)
        script, log = self._fake_app_server("stale")
        previous = self._environment(
            AGMSG_CODEX_APP_SERVER_CMD=f"{sys.executable} {script} stale {log}"
        )
        try:
            bridge = codex.CodexBridge(
                self.project,
                "team",
                "alice",
                timeout=1,
                interval=1,
                turn_timeout=1,
            )
            with self.assertRaises(AgmsgError) as raised:
                bridge.run()
            self.assertEqual(raised.exception.code, "stale_wakeup")
        finally:
            self._restore_environment(previous)

    def test_bridge_connects_over_websocket_unix_socket(self):
        identity.join("team", "alice", "codex", self.project)
        sock_path = str(Path(self.tmp) / "app-server.sock")
        methods = []
        server_errors = []
        ready = threading.Event()

        def recv_exact(conn, size):
            data = bytearray()
            while len(data) < size:
                chunk = conn.recv(size - len(data))
                if not chunk:
                    raise EOFError
                data.extend(chunk)
            return bytes(data)

        def recv_frame(conn):
            first, second = recv_exact(conn, 2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", recv_exact(conn, 2))[0]
            elif length == 127:
                length = struct.unpack("!Q", recv_exact(conn, 8))[0]
            mask = recv_exact(conn, 4) if second & 0x80 else b""
            payload = recv_exact(conn, length)
            if mask:
                payload = bytes(
                    value ^ mask[index % 4]
                    for index, value in enumerate(payload)
                )
            return first & 0x0F, payload

        def send_json(conn, value):
            payload = json.dumps(value).encode()
            if len(payload) < 126:
                header = bytes((0x81, len(payload)))
            else:
                header = bytes((0x81, 126)) + struct.pack("!H", len(payload))
            conn.sendall(header + payload)

        def server():
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(sock_path)
            except OSError as exc:
                server_errors.append(exc)
                listener.close()
                ready.set()
                return
            listener.listen(1)
            ready.set()
            conn, _ = listener.accept()
            try:
                header = bytearray()
                while b"\r\n\r\n" not in header:
                    header.extend(conn.recv(1))
                text = header.decode("latin1")
                key = next(
                    line.split(":", 1)[1].strip()
                    for line in text.split("\r\n")
                    if line.lower().startswith("sec-websocket-key:")
                )
                accept = base64.b64encode(
                    hashlib.sha1(
                        (
                            key
                            + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                        ).encode()
                    ).digest()
                ).decode()
                conn.sendall(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                    ).encode()
                )
                while True:
                    opcode, payload = recv_frame(conn)
                    if opcode == 0x8:
                        break
                    message = json.loads(payload)
                    method = message.get("method")
                    methods.append(method)
                    if method == "initialize":
                        send_json(
                            conn,
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "result": {},
                            },
                        )
                    elif method == "thread/resume":
                        send_json(
                            conn,
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "result": {
                                    "thread": {
                                        "id": message["params"]["threadId"],
                                        "status": {"type": "idle"},
                                    }
                                },
                            },
                        )
                    elif method == "process/spawn":
                        send_json(
                            conn,
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "result": {},
                            },
                        )
                        send_json(
                            conn,
                            {
                                "jsonrpc": "2.0",
                                "method": "process/exited",
                                "params": {
                                    "processHandle": message["params"][
                                        "processHandle"
                                    ],
                                    "exitCode": 0,
                                    "stdout": "status=pending count=1 max_id=1\n",
                                    "stderr": "",
                                },
                            },
                        )
                    elif method == "turn/start":
                        send_json(
                            conn,
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "result": {},
                            },
                        )
                        send_json(
                            conn,
                            {
                                "jsonrpc": "2.0",
                                "method": "turn/completed",
                                "params": {
                                    "threadId": message["params"]["threadId"]
                                },
                            },
                        )
                    elif method == "process/kill":
                        send_json(
                            conn,
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "result": {},
                            },
                        )
            except (EOFError, OSError):
                pass
            finally:
                conn.close()
                listener.close()

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2))
        if server_errors:
            self.skipTest(
                f"Unix socket listen is unavailable in this sandbox: "
                f"{server_errors[0]}"
            )
        bridge = codex.CodexBridge(
            self.project,
            "team",
            "alice",
            thread_id="thread-existing",
            app_server=f"unix://{sock_path}",
            timeout=1,
            interval=1,
            max_wakes=1,
            turn_timeout=1,
        )
        self.assertEqual(bridge.run(), 0)
        thread.join(timeout=2)
        self.assertIn("initialize", methods)
        self.assertIn("thread/resume", methods)
        self.assertIn("process/spawn", methods)
        self.assertIn("turn/start", methods)


if __name__ == "__main__":
    unittest.main()
