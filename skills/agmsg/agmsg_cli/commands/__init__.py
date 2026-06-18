"""Command implementations and the dispatch table.

Public commands: install, whoami, join, leave, inbox, send, history, team,
rename, rename-team, reset, spawn, config, delivery, actas, drop.
Internal (hook/runtime) commands: identities, watch, session-start,
session-end, check-inbox, watch-once, codex-bridge,
codex-bridge-launcher, codex-shim.

A handler returns either a result dict ``{"human": str, "data": Any}`` (the
dispatcher renders it via the envelope) or an ``int`` exit code (the handler
already wrote its own, protocol-specific, stdout).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

from .. import config as configmod
from .. import codex, delivery, identity, install, spawn, storage
from .. import platform as plat
from ..envelope import AgmsgError


def _need(args: list[str], n: int, usage: str) -> None:
    if len(args) < n:
        raise AgmsgError("bad_args", f"usage: {usage}", 2)


def _opts(args: list[str], flags: dict[str, str]) -> tuple[list[str], dict[str, Any]]:
    """Split argv into positionals and ``--flag value`` / bool options.

    ``flags`` maps flag name -> "value" | "bool".
    """
    pos: list[str] = []
    out: dict[str, Any] = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a in flags:
            kind = flags[a]
            name = a.lstrip("-")
            if kind == "bool":
                out[name] = True
                i += 1
            else:
                if i + 1 >= len(args):
                    raise AgmsgError("bad_args", f"{a} needs a value", 2)
                out[name] = args[i + 1]
                i += 2
        else:
            pos.append(a)
            i += 1
    return pos, out


# --------------------------------------------------------------------------- #
# install / identity


def cmd_install(args, as_json):
    return install.run(args)


def cmd_whoami(args, as_json):
    _need(args, 1, "whoami <project> [type]")
    project = args[0]
    agent_type = args[1] if len(args) > 1 else plat.detect_agent_type()
    plat.require_agent_type(agent_type)
    return identity.whoami(project, agent_type)


def cmd_join(args, as_json):
    _need(args, 4, "join <team> <agent> <type> <project>")
    return identity.join(args[0], args[1], args[2], args[3])


def cmd_leave(args, as_json):
    _need(args, 2, "leave <team> <agent>")
    return identity.leave(args[0], args[1])


def cmd_identities(args, as_json):
    _need(args, 2, "identities <project> <type>")
    pairs = identity.identities(args[0], args[1])
    human = "\n".join(f"{t}\t{a}" for t, a in pairs)
    return {"human": human, "data": [{"team": t, "agent": a} for t, a in pairs]}


def cmd_team(args, as_json):
    _need(args, 1, "team <team>")
    return identity.team_info(args[0])


def cmd_rename(args, as_json):
    _need(args, 3, "rename <team> <old> <new>")
    return identity.rename(args[0], args[1], args[2])


def cmd_rename_team(args, as_json):
    _need(args, 2, "rename-team <old> <new>")
    return identity.rename_team(args[0], args[1])


def cmd_reset(args, as_json):
    _need(args, 2, "reset <project> <type> [agent] [session]")
    project, agent_type = args[0], args[1]
    agent = args[2] if len(args) > 2 else None
    session = args[3] if len(args) > 3 else None
    return identity.reset(project, agent_type, agent, session)


# --------------------------------------------------------------------------- #
# messaging


def cmd_send(args, as_json):
    _need(args, 4, "send <team> <from> <to> <message>")
    team, frm, to, body = args[0], args[1], args[2], args[3]
    storage.send(team, frm, to, body)
    return {
        "human": f"Sent to {to} in team {team}",
        "data": {"team": team, "from": frm, "to": to},
    }


def cmd_inbox(args, as_json):
    pos, opts = _opts(args, {"--quiet": "bool"})
    _need(pos, 2, "inbox <team> <agent> [--quiet]")
    team, agent = pos[0], pos[1]
    quiet = opts.get("quiet", False)
    if not storage.db_exists():
        if quiet:
            return {"human": "", "data": {"messages": []}}
        return {"human": "No messages (DB not initialized)", "data": {"messages": []}}
    rows = storage.unread(team, agent)
    data = [
        {"from": r["from_agent"], "body": r["body"], "created_at": r["created_at"]}
        for r in rows
    ]
    if not rows:
        human = "" if quiet else "No new messages."
        return {"human": human, "data": {"messages": []}}
    lines = [f"{len(rows)} new message(s):", ""]
    for r in rows:
        body = r["body"].replace("\n", "\\n").replace("\t", "\\t")
        lines.append(f"  [{r['created_at']}] {r['from_agent']}: {body}")
    lines.append("")
    storage.mark_read(team, agent)
    return {"human": "\n".join(lines), "data": {"messages": data}}


def cmd_history(args, as_json):
    _need(args, 1, "history <team> [agent] [limit]")
    team = args[0]
    agent = args[1] if len(args) > 1 and args[1] else None
    limit = int(args[2]) if len(args) > 2 and args[2].isdigit() else 20
    if not storage.db_exists():
        return {"human": "No messages (DB not initialized)", "data": {"messages": []}}
    rows = storage.history(team, agent, limit)
    if not rows:
        return {"human": "No message history.", "data": {"messages": []}}
    lines = []
    data = []
    for r in rows:
        glyph = "●" if r["read_at"] is None else "○"
        body = r["body"].replace("\n", "\\n").replace("\t", "\\t")
        lines.append(
            f"  {glyph} [{r['created_at']}] {r['from_agent']} → {r['to_agent']}: {body}"
        )
        data.append(
            {
                "from": r["from_agent"],
                "to": r["to_agent"],
                "body": r["body"],
                "created_at": r["created_at"],
                "read": r["read_at"] is not None,
            }
        )
    return {"human": "\n".join(lines), "data": {"messages": data}}


# --------------------------------------------------------------------------- #
# config / delivery


def cmd_config(args, as_json):
    _need(args, 1, "config show|get <key> [default]|set <key> <value>")
    action = args[0]
    if action == "show":
        return {"human": configmod.show_text(), "data": configmod.load()}
    if action == "get":
        _need(args, 2, "config get <key> [default]")
        default = args[2] if len(args) > 2 else None
        value = configmod.get(args[1], default)
        return {"human": "" if value is None else str(value), "data": {"value": value}}
    if action == "set":
        _need(args, 3, "config set <key> <value>")
        value = configmod.set_value(args[1], args[2])
        return {"human": f"Set {args[1]} = {value}", "data": {"key": args[1], "value": value}}
    raise AgmsgError("bad_args", f"Unknown config action: {action} (use get|set|show)", 2)


def cmd_delivery(args, as_json):
    _need(args, 1, "delivery set|status|stop|restart ...")
    action = args[0]
    rest = args[1:]
    if action == "set":
        _need(rest, 3, "delivery set <mode> <type> <project>")
        mode, agent_type, project = rest[0], rest[1], rest[2]
        plat.require_agent_type(agent_type)
        human = delivery.do_set(mode, agent_type, project)
        return {"human": human, "data": {"mode": mode, "type": agent_type, "project": project}}
    if action == "status":
        if len(rest) >= 2:
            human = delivery.do_status(rest[0], rest[1])
            return {"human": human, "data": {"mode": delivery.status_mode(rest[0], rest[1])}}
        return {"human": "mode: (project required)", "data": {}}
    if action == "stop":
        killed = delivery.kill_all_watchers()
        human = f"Killed {killed} watch process(es)." + "\n" + delivery.emit_stop_directive()
        return {"human": human, "data": {"killed": killed}}
    if action == "restart":
        killed = delivery.kill_all_watchers()
        lines = [f"Killed {killed} watch process(es)."]
        if len(rest) >= 2:
            lines.append(delivery.emit_stop_directive())
            lines.append(delivery.emit_monitor_directive(rest[0], rest[1]))
        return {"human": "\n".join(lines), "data": {"killed": killed}}
    raise AgmsgError("bad_args", f"Unknown delivery action: {action}", 2)


# --------------------------------------------------------------------------- #
# spawn / actas / drop


def cmd_spawn(args, as_json):
    pos, opts = _opts(
        args,
        {
            "--project": "value",
            "--team": "value",
            "--window": "bool",
            "--split": "value",
        },
    )
    _need(pos, 2, "spawn <claude-code|codex> <name> [--project P] [--team T] [--window] [--split h|v]")
    return spawn.spawn(
        pos[0],
        pos[1],
        project=opts.get("project"),
        team=opts.get("team"),
        window=opts.get("window", False),
        split=opts.get("split", "h"),
    )


def cmd_actas(args, as_json):
    pos, opts = _opts(args, {"--project": "value", "--type": "value", "--team": "value"})
    _need(pos, 1, "actas <name> [--project P] [--type T] [--team TEAM]")
    name = pos[0]
    project = opts.get("project", os.getcwd())
    agent_type = opts.get("type") or plat.detect_agent_type()
    plat.require_agent_type(agent_type)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    pairs = [(t, a) for (t, a) in identity.identities(project, agent_type) if a == name]
    if not pairs:
        team = opts.get("team")
        if not team:
            raise AgmsgError(
                "not_registered",
                f"actas '{name}' is not registered for this project; pass --team",
                2,
            )
        identity.join(team, name, agent_type, project)
        pairs = [(team, name)]

    teams = [t for t, _ in pairs]
    if agent_type == "claude-code" and session:
        from .. import locking

        # Record this session under its Claude Code process FIRST, so the lock
        # we are about to take proves alive even in turn mode (no SessionStart
        # hook) and cannot be reclaimed as stale by another session.
        delivery.register_session(session)
        claimed = []
        for team, _ in pairs:
            res = locking.claim(team, name, session)
            if res.startswith("held:"):
                for c in claimed:
                    locking.release(c, name, session)
                raise AgmsgError(
                    "held",
                    f"status=held team={team} owner={res.split(':', 1)[1]}",
                )
            claimed.append(team)
        directive = (
            f"\nAGMSG-DIRECTIVE: stop any existing 'agmsg inbox stream' Monitor "
            "(TaskList -> TaskStop), then invoke the Monitor tool with:\n"
            f"  command: {plat.python_executable()} {plat.agmsg_py()} watch "
            f"{session} {project} {agent_type} {name}\n"
            "  description: agmsg inbox stream\n"
            "  persistent: true\n"
            f"Use {name} as the sender for replies."
        )
        human = f"actas {name}: claimed in {', '.join(teams)}.{directive}"
    else:
        human = (
            f"actas {name}: using '{name}' as sender for this session "
            f"(teams: {', '.join(teams)})."
        )
    return {"human": human, "data": {"name": name, "teams": teams, "status": "ok"}}


def cmd_drop(args, as_json):
    pos, opts = _opts(args, {"--project": "value", "--type": "value"})
    _need(pos, 1, "drop <name> [--project P] [--type T]")
    name = pos[0]
    project = opts.get("project", os.getcwd())
    agent_type = opts.get("type") or plat.detect_agent_type()
    plat.require_agent_type(agent_type)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    result = identity.reset(project, agent_type, name, session)
    human = result["human"]
    if agent_type == "claude-code":
        human += (
            "\n" + delivery.emit_stop_directive()
            + "\n" + delivery.emit_monitor_directive(agent_type, project)
        )
    return {"human": human, "data": result["data"]}


# --------------------------------------------------------------------------- #
# hook runtime (internal)


def cmd_watch(args, as_json):
    _need(args, 3, "watch <session_id> <project> <type> [name]")
    name = args[3] if len(args) > 3 else None
    return delivery.run_watch(args[0], args[1], args[2], name)


def cmd_session_start(args, as_json):
    _need(args, 2, "session-start <type> <project>")
    hook_input = "" if sys.stdin.isatty() else sys.stdin.read()
    out = delivery.session_start(args[0], args[1], hook_input)
    if out:
        sys.stdout.write(out + "\n")
    return 0


def cmd_session_end(args, as_json):
    _need(args, 2, "session-end <type> <project>")
    hook_input = "" if sys.stdin.isatty() else sys.stdin.read()
    delivery.session_end(args[0], args[1], hook_input)
    return 0


def cmd_check_inbox(args, as_json):
    _need(args, 2, "check-inbox <type> <project>")
    agent_type, project = args[0], args[1]
    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    if raw and '"stop_hook_active"' in raw and "true" in raw:
        return 0
    kind, text = delivery.check_inbox(agent_type, project, raw)
    if kind == "messages":
        sys.stdout.write(
            json.dumps({"decision": "block", "reason": text}, ensure_ascii=False)
            + "\n"
        )
    elif kind == "defer":
        # A Monitor watcher owns delivery for this session: stay silent.
        pass
    elif agent_type == "codex":
        msg = (
            "agmsg: check skipped (cooldown)"
            if kind == "cooldown"
            else "agmsg: no new messages"
        )
        sys.stdout.write(
            json.dumps(
                {"continue": True, "systemMessage": msg}, ensure_ascii=False
            )
            + "\n"
        )
    return 0


def _positive_int(value: str, option: str, *, allow_zero: bool = False) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise AgmsgError("bad_args", f"{option} must be an integer", 2)
    if parsed < 0 or (parsed == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise AgmsgError("bad_args", f"{option} must be a {qualifier} integer", 2)
    return parsed


def cmd_watch_once(args, as_json):
    pos, opts = _opts(
        args,
        {
            "--team": "value",
            "--name": "value",
            "--timeout": "value",
            "--interval": "value",
        },
    )
    _need(
        pos,
        2,
        "watch-once <project> <type> [--team T] [--name N] "
        "[--timeout SEC] [--interval SEC]",
    )
    timeout = _positive_int(opts.get("timeout", "300"), "--timeout")
    interval = _positive_int(opts.get("interval", "2"), "--interval")
    return codex.watch_once(
        pos[0],
        pos[1],
        team=opts.get("team"),
        name=opts.get("name"),
        timeout=timeout,
        interval=interval,
    )


def cmd_codex_bridge(args, as_json):
    pos, opts = _opts(
        args,
        {
            "--project": "value",
            "--type": "value",
            "--team": "value",
            "--name": "value",
            "--timeout": "value",
            "--interval": "value",
            "--max-wakes": "value",
            "--stale-wake-limit": "value",
            "--turn-timeout": "value",
            "--app-server": "value",
            "--thread": "value",
            "--inline-inbox": "bool",
            "--resolve-only": "bool",
        },
    )
    if pos:
        raise AgmsgError("bad_args", f"unknown option: {pos[0]}", 2)
    project = opts.get("project")
    if not project:
        raise AgmsgError("bad_args", "--project is required", 2)
    project = os.path.realpath(project)
    if not os.path.isdir(project):
        raise AgmsgError(
            "bad_project", f"project path is not a directory: {project}", 2
        )
    thread = opts.get("thread")
    if thread == "current":
        thread = os.environ.get("CODEX_THREAD_ID")
        if not thread:
            raise AgmsgError(
                "bad_args", "--thread current requires CODEX_THREAD_ID", 2
            )
    options = {
        "project": project,
        "type": opts.get("type", "codex"),
        "team": opts.get("team"),
        "name": opts.get("name"),
        "timeout": _positive_int(opts.get("timeout", "300"), "--timeout"),
        "interval": _positive_int(opts.get("interval", "2"), "--interval"),
        "max_wakes": _positive_int(
            opts.get("max-wakes", "0"), "--max-wakes", allow_zero=True
        ),
        "stale_wake_limit": _positive_int(
            opts.get("stale-wake-limit", "1"),
            "--stale-wake-limit",
            allow_zero=True,
        ),
        "turn_timeout": _positive_int(
            opts.get("turn-timeout", "60"),
            "--turn-timeout",
            allow_zero=True,
        ),
        "app_server": opts.get("app-server"),
        "thread": thread,
        "inline_inbox": opts.get("inline-inbox", False),
        "resolve_only": opts.get("resolve-only", False),
    }
    return codex.run_bridge(options)


def cmd_codex_bridge_launcher(args, as_json):
    _need(
        args,
        4,
        "codex-bridge-launcher <type> <project> <app-server> <parent-pid>",
    )
    parent_pid = _positive_int(args[3], "<parent-pid>")
    return codex.bridge_launcher(args[0], args[1], args[2], parent_pid)


def cmd_codex_monitor(args, as_json):
    before, after = args, []
    if "--" in args:
        index = args.index("--")
        before, after = args[:index], args[index + 1 :]
    pos, opts = _opts(
        before,
        {
            "--project": "value",
            "--socket-path": "value",
            "--codex-command": "value",
        },
    )
    if pos:
        raise AgmsgError("bad_args", f"unknown option: {pos[0]}", 2)
    return codex.run_monitor(
        opts.get("project", os.getcwd()),
        opts.get("codex-command", "resume"),
        after,
        opts.get("socket-path"),
    )


def cmd_codex_shim(args, as_json):
    return codex.run_shim(args)


def cmd_codex_shim_install(args, as_json):
    action = args[0] if args else "install"
    if action == "install":
        target, on_path = codex.install_shim()
        lines = [f"installed: {target}"]
        if not on_path:
            lines.append(f"note: add {target.parent} before the real Codex on PATH")
        return {
            "human": "\n".join(lines),
            "data": {"installed": True, "path": str(target), "on_path": on_path},
        }
    if action in ("remove", "uninstall"):
        removed = codex.remove_shim()
        return {
            "human": (
                f"removed: {codex.shim_target()}"
                if removed
                else f"not installed: {codex.shim_target()}"
            ),
            "data": {"removed": removed},
        }
    if action == "status":
        target = codex.shim_target()
        installed = codex._is_our_shim(target)
        return {
            "human": (
                f"installed: {target}" if installed else f"not installed: {target}"
            ),
            "data": {"installed": installed, "path": str(target)},
        }
    raise AgmsgError(
        "bad_args", "usage: codex-shim-install [install|remove|status]", 2
    )


COMMANDS: dict[str, Callable[[list[str], bool], Any]] = {
    "install": cmd_install,
    "whoami": cmd_whoami,
    "join": cmd_join,
    "leave": cmd_leave,
    "inbox": cmd_inbox,
    "send": cmd_send,
    "history": cmd_history,
    "team": cmd_team,
    "rename": cmd_rename,
    "rename-team": cmd_rename_team,
    "reset": cmd_reset,
    "spawn": cmd_spawn,
    "config": cmd_config,
    "delivery": cmd_delivery,
    "actas": cmd_actas,
    "drop": cmd_drop,
    # internal
    "identities": cmd_identities,
    "watch": cmd_watch,
    "session-start": cmd_session_start,
    "session-end": cmd_session_end,
    "check-inbox": cmd_check_inbox,
    "watch-once": cmd_watch_once,
    "codex-bridge": cmd_codex_bridge,
    "codex-bridge-launcher": cmd_codex_bridge_launcher,
    "codex-monitor": cmd_codex_monitor,
    "codex-shim": cmd_codex_shim,
    "codex-shim-install": cmd_codex_shim_install,
}
