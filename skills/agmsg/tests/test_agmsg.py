"""Unit + integration tests for the agmsg Python CLI.

Run from the skill dir:  python3 -m unittest discover -s tests
OS-specific spawn paths are covered with mocks (no real terminals launched).
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from agmsg_cli import commands, config, delivery, identity, locking, spawn, storage  # noqa: E402
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

    def test_codex_rejects_monitor(self):
        with self.assertRaises(AgmsgError):
            delivery.apply("monitor", "codex", self.project)

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


if __name__ == "__main__":
    unittest.main()
