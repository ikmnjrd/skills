"""Delivery modes, hook-file generation, and the hook runtime.

Mode is not stored as a field — it is implicit in which agmsg-owned hook
entries exist in the per-project hook file:
  - claude-code -> <project>/.claude/settings.local.json
  - codex       -> <project>/.codex/hooks.json

Valid modes: claude-code = monitor|turn|both|off;
codex = monitor|turn|off (monitor is an experimental app-server bridge).

Hook commands invoke this same CLI via the recorded absolute Python +
agmsg.py paths, e.g. ``<python> <agmsg.py> check-inbox <type> <project>``.
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import config, identity, locking, storage
from . import platform as plat
from .envelope import AgmsgError
from .jsonio import atomic_write_json

EVENTS = ("SessionStart", "SessionEnd", "Stop")
_OWNED_MARKERS = ("agmsg.py", "/agmsg/scripts/")

VALID_MODES = {
    "claude-code": ("monitor", "turn", "both", "off"),
    "codex": ("monitor", "turn", "off"),
}


# --------------------------------------------------------------------------- #
# helpers


def hooks_file(agent_type: str, project: str) -> Path:
    if agent_type == "claude-code":
        return Path(project) / ".claude" / "settings.local.json"
    if agent_type == "codex":
        return Path(project) / ".codex" / "hooks.json"
    raise AgmsgError("bad_agent_type", f"Unknown agent type: {agent_type}")


def hook_command(subcommand: str, agent_type: str, project: str) -> str:
    parts = [
        plat.python_executable(),
        str(plat.agmsg_py()),
        subcommand,
        agent_type,
        project,
    ]
    return " ".join(shlex.quote(p) for p in parts)


def _entry(cmd: str) -> dict:
    return {"matcher": "", "hooks": [{"type": "command", "command": cmd}]}


def _is_owned(entry: dict) -> bool:
    for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
        command = str(hook.get("command", ""))
        if any(marker in command for marker in _OWNED_MARKERS):
            return True
    return False


def _strip_owned(hooks: dict) -> None:
    for event in EVENTS:
        arr = hooks.get(event)
        if isinstance(arr, list):
            kept = [e for e in arr if not _is_owned(e)]
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)


def _load_json(path: Path) -> dict:
    """Load an existing hook file. A missing file is an empty document; a
    present-but-unreadable/invalid file is a hard error so we never silently
    discard and overwrite the user's hook configuration."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgmsgError("hook_read_error", f"cannot read hook file {path}: {exc}")
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise AgmsgError(
            "hook_parse_error",
            f"hook file {path} is not valid JSON; refusing to modify it "
            f"({exc}). Fix or remove the file and retry.",
        )
    if not isinstance(parsed, dict):
        raise AgmsgError(
            "hook_type_error",
            f"hook file {path} must be a JSON object, got "
            f"{type(parsed).__name__}; refusing to modify it.",
        )
    return parsed


def _write_json(path: Path, data: dict) -> None:
    """Atomically replace the hook file (temp + fsync + os.replace)."""
    atomic_write_json(path, data, error_code="hook_write_error")


# --------------------------------------------------------------------------- #
# apply / status


def apply(mode: str, agent_type: str, project: str) -> None:
    valid = VALID_MODES.get(agent_type)
    if valid is None:
        raise AgmsgError("bad_agent_type", f"Unknown agent type: {agent_type}")
    if mode not in valid:
        raise AgmsgError(
            "bad_mode",
            f"'{mode}' mode is not supported for {agent_type} "
            f"(use {'|'.join(valid)})",
        )

    path = hooks_file(agent_type, project)
    data = _load_json(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    _strip_owned(hooks)

    if mode in ("monitor", "both"):
        hooks.setdefault("SessionStart", []).append(
            _entry(hook_command("session-start", agent_type, project))
        )
        hooks.setdefault("SessionEnd", []).append(
            _entry(hook_command("session-end", agent_type, project))
        )
        # The Codex app-server bridge only exists when Codex was launched
        # through the generated shim. Keep a Stop-hook fallback so Desktop,
        # an incorrectly ordered PATH, or a failed bridge does not silently
        # leave messages unread. check_inbox() defers while a bridge is live.
        if agent_type == "codex":
            hooks.setdefault("Stop", []).append(
                _entry(hook_command("check-inbox", agent_type, project))
            )
    if mode in ("turn", "both"):
        hooks.setdefault("Stop", []).append(
            _entry(hook_command("check-inbox", agent_type, project))
        )

    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    _write_json(path, data)


def status_mode(agent_type: str, project: str) -> str:
    path = hooks_file(agent_type, project)
    hooks = _load_json(path).get("hooks")
    if not isinstance(hooks, dict):
        return "off"
    has_ss = any(_is_owned(e) for e in hooks.get("SessionStart", []) or [])
    has_st = any(_is_owned(e) for e in hooks.get("Stop", []) or [])
    if agent_type == "codex" and has_ss:
        # Codex monitor intentionally includes a Stop fallback.
        return "monitor"
    if has_ss and has_st:
        return "both"
    if has_ss:
        return "monitor"
    if has_st:
        return "turn"
    return "off"


# --------------------------------------------------------------------------- #
# directives


def _resolve_session_id() -> str:
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        return sid
    return f"agmsg-{os.getpid()}"


def _watch_command(session_id: str, project: str, agent_type: str) -> str:
    return (
        f"{plat.python_executable()} {plat.agmsg_py()} watch "
        f"{session_id} {project} {agent_type}"
    )


def emit_monitor_directive(agent_type: str, project: str) -> str:
    sid = _resolve_session_id()
    pidfile = plat.run_dir() / f"watch.{sid}.pid"
    if pidfile.is_file():
        try:
            pid = int(pidfile.read_text(encoding="utf-8").strip())
            if locking._pid_alive(pid):
                return (
                    "\nA watch is already streaming into this session "
                    f"(pid {pid}). No action needed."
                )
        except (ValueError, OSError):
            pass
    return (
        "\nAGMSG-DIRECTIVE: For this running session, invoke the Monitor tool "
        "now with:\n"
        f"  command: {_watch_command(sid, project, agent_type)}\n"
        "  description: agmsg inbox stream\n"
        "  persistent: true\n\n"
        "Pass the command above verbatim — the session_id is already filled in."
    )


def emit_stop_directive() -> str:
    return (
        "\nAGMSG-DIRECTIVE: If an agmsg watch Monitor task is running in this "
        "session,\n"
        'find it with TaskList (description starts with "agmsg inbox stream")\n'
        "and stop it with TaskStop. Existing watch processes have already been\n"
        "killed by this command."
    )


# --------------------------------------------------------------------------- #
# watcher process management


def _watch_pidfiles() -> list[Path]:
    run = plat.run_dir()
    if not run.is_dir():
        return []
    return list(run.glob("watch.*.pid"))


def _proc_cmdline(pid: int) -> str:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _find_cc_pid() -> int | None:
    """Walk the parent chain for the enclosing Claude Code process.

    The cc-instance marker is keyed by this pid so a session_id can be proven
    "alive" by ``locking.sid_alive`` and so re-fires (e.g. /clear) within the
    same CC process are detected.
    """
    pid = os.getpid()
    for _ in range(20):
        if pid <= 1:
            break
        first = _proc_cmdline(pid).split(" ", 1)[0]
        if os.path.basename(first) == "claude":
            return pid
        pid = plat._proc_ppid(pid)
    return None


def _kill_watcher(sid: str) -> None:
    """Stop the watcher owning ``sid`` (if it is one of ours) and drop its pidfile."""
    if not sid:
        return
    pidfile = plat.run_dir() / f"watch.{sid}.pid"
    if not pidfile.is_file():
        return
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        if locking._pid_alive(pid) and str(plat.agmsg_py()) in _proc_cmdline(pid):
            os.kill(pid, signal.SIGTERM)
    except (ValueError, OSError):
        pass
    try:
        pidfile.unlink()
    except OSError:
        pass


def _cc_instance_bookkeeping(sid: str, cc_pid: int | None) -> None:
    """Record this session under its CC process and reap orphaned watchers.

    - Drop ``cc-instance.<pid>`` files for dead CC processes, killing any
      watcher whose sid no longer belongs to a live CC instance.
    - Remove stale ``watch.*.pid`` files for dead watchers.
    - On a re-fire within the same CC process (same cc_pid, new sid), stop the
      previous session's watcher before recording the new sid.
    """
    run = plat.run_dir()
    run.mkdir(parents=True, exist_ok=True)

    live_sids: set[str] = set()
    for entry in run.glob("cc-instance.*"):
        suffix = entry.name.rsplit(".", 1)[-1]
        if suffix.isdigit() and locking._pid_alive(int(suffix)):
            try:
                live_sids.add(entry.read_text(encoding="utf-8").strip())
            except OSError:
                pass

    for entry in run.glob("cc-instance.*"):
        suffix = entry.name.rsplit(".", 1)[-1]
        if not suffix.isdigit() or locking._pid_alive(int(suffix)):
            continue
        try:
            dead_sid = entry.read_text(encoding="utf-8").strip()
        except OSError:
            dead_sid = ""
        if dead_sid and dead_sid not in live_sids:
            _kill_watcher(dead_sid)
        try:
            entry.unlink()
        except OSError:
            pass

    for pidfile in run.glob("watch.*.pid"):
        try:
            pid = int(pidfile.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pid = -1
        if pid < 0 or not locking._pid_alive(pid):
            try:
                pidfile.unlink()
            except OSError:
                pass

    if cc_pid:
        inst = run / f"cc-instance.{cc_pid}"
        if inst.is_file():
            try:
                prev = inst.read_text(encoding="utf-8").strip()
            except OSError:
                prev = ""
            if prev and prev != sid:
                _kill_watcher(prev)
        inst.write_text(sid + "\n", encoding="utf-8")


def register_session(session_id: str) -> None:
    """Record the current session under its enclosing Claude Code process.

    Shared by the SessionStart hook (monitor/both) and ``actas`` (which must
    register even in turn mode, where SessionStart never fires) so the
    session's actas locks prove alive via ``locking.sid_alive``.
    """
    if not session_id:
        return
    _cc_instance_bookkeeping(session_id, _find_cc_pid())


def kill_all_watchers(project: str | None = None) -> int:
    killed = 0
    marker = str(plat.agmsg_py())
    for pidfile in _watch_pidfiles():
        try:
            pid = int(pidfile.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            try:
                pidfile.unlink()
            except OSError:
                pass
            continue
        if locking._pid_alive(pid):
            cmdline = _proc_cmdline(pid)
            if marker in cmdline:
                if project and f" {project} " not in f" {cmdline} ":
                    continue
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                except OSError:
                    pass
        try:
            pidfile.unlink()
        except OSError:
            pass
    return killed


# --------------------------------------------------------------------------- #
# set


def do_set(mode: str, agent_type: str, project: str) -> str:
    apply(mode, agent_type, project)
    lines = [f"Delivery mode set to '{mode}' for {project} ({agent_type})"]
    if mode in ("monitor", "both"):
        if agent_type == "codex":
            from . import codex

            cleaned = codex.cleanup_stale_bridges(project)
            if cleaned:
                lines.append(f"Removed {cleaned} stale Codex bridge state file(s).")
            try:
                target, on_path = codex.install_shim()
                lines.append(f"Codex monitor shim installed at {target}.")
                if on_path:
                    lines.append(
                        "Future Codex sessions: launch with codex; interactive "
                        "sessions in this project will use the monitor bridge."
                    )
                else:
                    lines.extend(
                        [
                            "WARNING: ~/.agents/bin is NOT on your PATH, so "
                            "'codex' still launches the real binary and the "
                            "monitor bridge will NOT engage.",
                            'Add this line, restart your shell, then launch with codex:',
                            '  export PATH="$HOME/.agents/bin:$PATH"',
                        ]
                    )
            except AgmsgError as exc:
                lines.append(
                    "Codex monitor mode is enabled, but the shim was not "
                    f"installed: {exc.message}"
                )
                lines.append(
                    f"Launch explicitly with: {plat.python_executable()} "
                    f"{plat.agmsg_py()} codex-monitor --project "
                    f"{shlex.quote(project)}"
                )
            lines.extend(
                [
                    "A Stop-hook fallback is enabled; sessions not attached to "
                    "the bridge will still receive messages between turns.",
                    "Restart Codex and send the first message; SessionStart "
                    "fires on that first turn.",
                    f"For more info: {codex.MONITOR_DOC_URL}",
                ]
            )
            return "\n".join(lines)
        lines.append(
            "Future sessions: SessionStart hook will auto-launch the watcher."
        )
        lines.append(emit_monitor_directive(agent_type, project))
    elif mode == "turn":
        lines.append("Future sessions: Stop hook will check inbox between turns.")
        if agent_type == "codex":
            from . import codex

            codex.stop_bridges(project)
        else:
            kill_all_watchers(project)
        lines.append(emit_stop_directive())
    else:  # off
        lines.append("Future sessions: no automatic delivery.")
        if agent_type == "codex":
            from . import codex

            killed = codex.stop_bridges(project)
            if killed:
                lines.append(
                    f"Stopped {killed} Codex bridge process(es) for this project."
                )
            lines.append(
                "The shared ~/.agents/bin/codex shim was left in place. "
                "Remove it with `agmsg.py codex-shim-install remove` when no "
                "project uses monitor mode."
            )
        else:
            kill_all_watchers(project)
        lines.append(emit_stop_directive())
    return "\n".join(lines)


def do_status(agent_type: str, project: str) -> str:
    mode = status_mode(agent_type, project)
    lines = [f"mode: {mode}"]
    path = hooks_file(agent_type, project)
    if path.is_file():
        hooks = _load_json(path).get("hooks", {})
        lines.append(f"settings hooks file: {path}")
        for event in EVENTS:
            count = len(hooks.get(event, []) or []) if isinstance(hooks, dict) else 0
            lines.append(f"  {event} entries: {count}")
    if agent_type == "codex":
        from . import codex

        shim = codex.shim_status()
        bridges = codex.bridge_status(project)
        lines.append(f"identities: {len(identity.identities(project, agent_type))}")
        lines.append(
            f"shim: {'installed' if shim['installed'] else 'not installed'} "
            f"at {shim['path']}"
        )
        lines.append(f"shim first on PATH: {'yes' if shim['on_path'] else 'no'}")
        if shim["resolved"]:
            lines.append(f"codex resolves to: {shim['resolved']}")
        lines.append(
            "bridge processes: "
            f"{bridges['alive']} alive, {bridges['stale']} stale"
        )
        configured_hooks = _load_json(path).get("hooks", {})
        stop_entries = (
            configured_hooks.get("Stop", [])
            if isinstance(configured_hooks, dict)
            else []
        )
        fallback = status_mode(agent_type, project) == "monitor" and any(
            _is_owned(e) for e in (stop_entries or [])
        )
        lines.append(f"turn fallback: {'enabled' if fallback else 'disabled'}")
        if mode == "monitor":
            if codex.is_desktop_session():
                health = "desktop fallback (UI-visible Stop hook delivery)"
            elif bridges["alive"]:
                health = "active"
            elif fallback:
                health = "degraded (turn fallback; bridge is not running)"
            else:
                health = "broken (bridge is not running and no fallback exists)"
            lines.append(f"health: {health}")
        return "\n".join(lines)

    alive = dead = 0
    for pidfile in _watch_pidfiles():
        try:
            pid = int(pidfile.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            dead += 1
            continue
        if locking._pid_alive(pid):
            alive += 1
        else:
            dead += 1
    lines.append(f"watch processes: {alive} alive, {dead} stale pidfiles")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# hook runtime: check-inbox (turn), session-start/end (monitor), watch (monitor)

_FS = "\n"


def _render_body_inbox(body: str) -> str:
    return body.replace("\n", "\\n").replace("\t", "\\t")


def check_inbox(agent_type: str, project: str, hook_input: str = "") -> tuple[str, str]:
    """Stop/turn hook delivery.

    Returns ``(kind, text)`` where kind is one of:
      - ``defer``    — a Monitor watcher owns this session (avoid double delivery)
      - ``cooldown`` — within the turn check interval; skip this turn
      - ``none``     — no new messages
      - ``messages`` — text holds the rendered unread digest
    """
    if agent_type == "codex":
        from . import codex

        if codex.bridge_status(project)["alive"]:
            if codex.is_desktop_session():
                codex.stop_bridges(project)
            else:
                return ("defer", "")
        # Codex Desktop cannot live-render turns created by a detached
        # app-server. Keep monitor mode UI-visible by using the Stop-hook
        # fallback instead of starting a hidden background bridge.
        if codex.is_desktop_session():
            pass
        elif codex.bridge_status(project)["alive"]:
            return ("defer", "")

    sid = _extract_session_id(hook_input) or os.environ.get(
        "CLAUDE_CODE_SESSION_ID", ""
    )
    # Defer to a live Monitor watcher for this session (e.g. mode = both).
    if sid:
        pidfile = plat.run_dir() / f"watch.{sid}.pid"
        if pidfile.is_file():
            try:
                pid = int(pidfile.read_text(encoding="utf-8").strip())
                if locking._pid_alive(pid):
                    return ("defer", "")
            except (ValueError, OSError):
                pass

    info = identity.whoami(project, agent_type)["data"]
    status = info["status"]
    if status in ("not_joined", "suggest"):
        return ("none", "")
    agent = info["agents"][0] if status == "multiple" else info["agent"]
    teams = info["teams"]
    if not agent or not teams:
        return ("none", "")

    # Per-turn cooldown.
    run = plat.run_dir()
    run.mkdir(parents=True, exist_ok=True)
    marker = run / f".lastcheck-{agent}"
    interval = config.get_int("delivery.turn.check_interval", 60)
    if marker.exists():
        try:
            if time.time() - marker.stat().st_mtime < interval:
                return ("cooldown", "")
        except OSError:
            pass
    marker.touch()

    chunks = []
    for team in teams:
        if sid and locking.state(team, agent, sid).startswith("other:"):
            continue
        rows = storage.unread(team, agent)
        if not rows:
            continue
        out = [f"{len(rows)} new message(s) in {team}:"]
        for row in rows:
            out.append(
                f"  [{row['created_at']}] {row['from_agent']}: "
                f"{_render_body_inbox(row['body'])}"
            )
        chunks.append("\n".join(out))
        storage.mark_read(team, agent)
    if chunks:
        return ("messages", "\n".join(chunks))
    return ("none", "")


def session_start(agent_type: str, project: str, hook_input: str = "") -> str:
    """SessionStart hook: emit the directive to launch the Monitor watcher."""
    if not identity.identities(project, agent_type):
        return ""
    if agent_type == "codex":
        from . import codex

        if os.environ.get("AGMSG_CODEX_BRIDGE") != "1":
            return ""
        if os.environ.get("AGMSG_CODEX_BRIDGE_LAUNCHER") == "1":
            codex.publish_session_request(project)
            return ""
        # Direct launch is retained for explicit/testing use. Normal monitor
        # sessions use the outside-sandbox launcher rendezvous above.
        pairs = identity.identities(project, agent_type)
        thread_id = codex.resolve_thread_id(project)
        endpoint = os.environ.get("AGMSG_CODEX_BRIDGE_APP_SERVER", "")
        if len(pairs) == 1 and thread_id and endpoint:
            team, name = pairs[0]
            log = codex.bridge_path(team, name, "log")
            command_override = os.environ.get("AGMSG_CODEX_BRIDGE_CMD")
            command = (
                shlex.split(command_override)
                if command_override
                else [
                    plat.python_executable(),
                    str(plat.agmsg_py()),
                    "codex-bridge",
                ]
            )
            command += [
                "--project", project,
                "--type", agent_type,
                "--team", team,
                "--name", name,
                "--thread", thread_id,
                "--app-server", endpoint,
                "--inline-inbox",
            ]
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("ab") as stream:
                subprocess.Popen(
                    command,
                    cwd=project,
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=stream,
                    start_new_session=True,
                )
        return ""
    sid = _extract_session_id(hook_input) or f"unknown-{os.getpid()}"
    register_session(sid)
    locking.gc_stale()
    return (
        "AGMSG monitor mode: invoke the Monitor tool now with the following\n"
        "parameters, before any other action in this session.\n\n"
        f"  command: {_watch_command(sid, project, agent_type)}\n"
        "  description: agmsg inbox stream\n"
        "  persistent: true\n\n"
        "This streams incoming agmsg messages into the session in real time.\n"
        "Each output line is one message: `<ts> | <team> | <from> → <to> | "
        "<body>`. React to messages as they arrive; reply with the send command."
    )


def session_end(agent_type: str, project: str, hook_input: str = "") -> str:
    """SessionEnd hook: stop this session's watcher and release locks."""
    if agent_type == "codex":
        from . import codex

        codex.stop_bridges(project)
    sid = _extract_session_id(hook_input)
    if not sid:
        return ""
    _kill_watcher(sid)
    # Drop any cc-instance markers that still point at this ended session.
    run = plat.run_dir()
    if run.is_dir():
        for entry in run.glob("cc-instance.*"):
            try:
                if entry.read_text(encoding="utf-8").strip() == sid:
                    entry.unlink()
            except OSError:
                pass
    locking.release_all(sid)
    return ""


def _extract_session_id(hook_input: str) -> str:
    if not hook_input:
        return ""
    try:
        data = json.loads(hook_input)
        if isinstance(data, dict) and isinstance(data.get("session_id"), str):
            return data["session_id"]
    except ValueError:
        pass
    return ""


def _render_body_watch(body: str) -> str:
    return body.replace("\r", "").replace("\n", "\\n")


def run_watch(
    session_id: str, project: str, agent_type: str, active_name: str | None = None
) -> int:
    """Long-running streaming watcher used by the Monitor tool."""
    run = plat.run_dir()
    run.mkdir(parents=True, exist_ok=True)
    pidfile = run / f"watch.{session_id}.pid"

    # Supersede any prior watcher for this session.
    if pidfile.is_file():
        try:
            prior = int(pidfile.read_text(encoding="utf-8").strip())
            if prior != os.getpid() and locking._pid_alive(prior):
                if str(plat.agmsg_py()) in _proc_cmdline(prior):
                    os.kill(prior, signal.SIGTERM)
        except (ValueError, OSError):
            pass
    pidfile.write_text(f"{os.getpid()}\n", encoding="utf-8")

    def _cleanup(*_a):
        try:
            if pidfile.is_file() and pidfile.read_text().strip() == str(os.getpid()):
                pidfile.unlink()
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGHUP, _cleanup)

    pairs = identity.identities(project, agent_type)
    if active_name:
        pairs = [(t, a) for (t, a) in pairs if a == active_name]

    held = []
    filtered = []
    for team, agent in pairs:
        st = locking.state(team, agent, session_id)
        if st.startswith("other:"):
            if active_name:
                held.append(f"{team}/{agent}")
            continue
        if active_name:
            res = locking.claim(team, agent, session_id)
            if res.startswith("held:"):
                held.append(f"{team}/{agent}")
                continue
        filtered.append((team, agent))

    if held:
        sys.stderr.write(
            "agmsg watch: cannot claim (held by other sessions): "
            + ", ".join(held)
            + "\n"
        )
        return 1
    if not filtered:
        if active_name:
            sys.stdout.write(
                f"agmsg watch: no registration for agent '{active_name}' in "
                f"{project} ({agent_type}); nothing to do\n"
            )
        else:
            sys.stdout.write(
                "agmsg watch: no available identities; nothing to do\n"
            )
        return 0

    interval = _watch_interval()
    last = storage.max_id(filtered)
    while True:
        for row in storage.poll(last, filtered):
            sys.stdout.write(
                f"{row['created_at']} | {row['team']} | "
                f"{row['from_agent']} → {row['to_agent']} | "
                f"{_render_body_watch(row['body'])}\n"
            )
            sys.stdout.flush()
            last = row["id"]
        time.sleep(interval)


def _watch_interval() -> int:
    env = os.environ.get("AGMSG_WATCH_INTERVAL")
    if env and env.isdigit():
        return int(env)
    return config.get_int("delivery.monitor.poll_interval", 5)
