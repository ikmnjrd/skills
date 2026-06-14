"""Spawn a peer agent (claude-code/codex) into a new tmux pane/window or a
new OS terminal, pre-joined to a team and booting straight into ``actas``.

No generated shell boot script and no free-form terminal template: each target
is launched with an explicit ``subprocess`` argv array. Linux + macOS only.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from . import identity, locking
from . import platform as plat
from .envelope import AgmsgError

_CLI_BIN = {"claude-code": "claude", "codex": "codex"}

# Indirection point so tests can capture launches without spawning processes.
_runner = None


def _run(argv: list[str], cwd: str | None = None) -> None:
    if _runner is not None:
        _runner(argv, cwd)
        return
    subprocess.Popen(  # noqa: S603 - args are argv arrays, no shell
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _resolve_team(project: str) -> str:
    teams = plat.teams_dir()
    candidates = []
    if teams.is_dir():
        for team_dir in sorted(teams.iterdir()):
            cfg = team_dir / "config.json"
            if not cfg.is_file():
                continue
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            for entry in data.get("agents", {}).values():
                regs = entry.get("registrations")
                if not isinstance(regs, list):
                    regs = [entry]
                if any(r.get("project") == project for r in regs):
                    candidates.append(data.get("name") or team_dir.name)
                    break
    candidates = sorted(set(candidates))
    if not candidates:
        raise AgmsgError(
            "no_team",
            "no team is registered for this project; pass --team <team>",
        )
    if len(candidates) > 1:
        raise AgmsgError(
            "ambiguous_team",
            "project belongs to multiple teams "
            f"({', '.join(candidates)}); pass --team <team>",
        )
    return candidates[0]


def tmux_commands(
    name: str, project: str, bin_argv: list[str], window: bool, split: str
) -> list[list[str]]:
    if window:
        return [
            ["tmux", "new-window", "-n", name, "-c", project, *bin_argv],
        ]
    direction = "-v" if split == "v" else "-h"
    return [["tmux", "split-window", direction, "-c", project, *bin_argv]]


def linux_terminal_argv(project: str, bin_argv: list[str]) -> list[str]:
    if shutil.which("gnome-terminal"):
        return ["gnome-terminal", f"--working-directory={project}", "--", *bin_argv]
    if shutil.which("konsole"):
        return ["konsole", "--workdir", project, "-e", *bin_argv]
    for term in ("x-terminal-emulator", "xfce4-terminal", "xterm"):
        if shutil.which(term):
            return [term, "-e", *bin_argv]
    raise AgmsgError(
        "no_terminal",
        "no supported terminal emulator found "
        "(tried gnome-terminal/konsole/xterm/...); run inside tmux",
    )


def macos_terminal_argv(project: str, bin_argv: list[str]) -> list[str]:
    inner = f"cd {shlex.quote(project)} && exec " + " ".join(
        shlex.quote(a) for a in bin_argv
    )
    app = "iTerm" if os.environ.get("TERM_PROGRAM") == "iTerm.app" else "Terminal"
    script = f'tell application "{app}" to do script "{inner}"'
    return ["osascript", "-e", script]


def spawn(
    agent_type: str,
    name: str,
    project: str | None = None,
    team: str | None = None,
    window: bool = False,
    split: str = "h",
) -> dict:
    if agent_type not in _CLI_BIN:
        raise AgmsgError(
            "bad_agent_type",
            f"unknown agent type '{agent_type}' (supported: claude-code, codex)",
        )
    if split not in ("h", "v"):
        raise AgmsgError("bad_split", "--split must be 'h' or 'v'")

    project = project or os.getcwd()
    p = Path(project)
    if not p.is_dir():
        raise AgmsgError("no_project", f"project path does not exist: {project}")
    project = str(p.resolve())

    cli_bin = _CLI_BIN[agent_type]
    if not shutil.which(cli_bin):
        raise AgmsgError(
            "no_cli",
            f"'{cli_bin}' not found on PATH — install the {agent_type} CLI first",
        )

    if not team:
        team = _resolve_team(project)

    st = locking.state(team, name, "")
    if st.startswith("other:"):
        raise AgmsgError(
            "held",
            f"actas '{name}' in team '{team}' is held by a live session "
            f"({st.split(':', 1)[1]}); drop it there first",
        )

    identity.join(team, name, agent_type, project)

    cmd_name = plat.skill_dir().name
    # claude-code invokes skills with a leading slash (/agmsg ...); codex uses
    # a leading dollar ($agmsg ...). See SKILL.claude-code.md / SKILL.codex.md.
    invocation_prefix = "/" if agent_type == "claude-code" else "$"
    prompt = f"{invocation_prefix}{cmd_name} actas {name}"
    bin_argv = [cli_bin, prompt]

    if os.environ.get("TMUX"):
        if not shutil.which("tmux"):
            raise AgmsgError(
                "no_tmux",
                "$TMUX is set but the tmux binary is not on PATH",
            )
        for argv in tmux_commands(name, project, bin_argv, window, split):
            _run(argv, cwd=project)
        target = "window" if window else "pane"
        human = f"spawned {agent_type} '{name}' in tmux ({target})"
        mode = f"tmux:{target}"
    else:
        osn = plat.os_name()
        if osn == "linux":
            if not os.environ.get("DISPLAY") and not os.environ.get(
                "WAYLAND_DISPLAY"
            ):
                raise AgmsgError(
                    "headless",
                    "headless environment: no tmux session and no display "
                    "available — run inside tmux",
                )
            argv = linux_terminal_argv(project, bin_argv)
        elif osn == "macos":
            argv = macos_terminal_argv(project, bin_argv)
        else:
            raise AgmsgError(
                "unsupported_os",
                f"unsupported platform '{osn}' for the non-tmux path; "
                "run inside tmux",
            )
        _run(argv, cwd=project)
        human = f"spawned {agent_type} '{name}' in a new terminal window"
        mode = f"terminal:{osn}"

    return {
        "human": human,
        "data": {"agent": agent_type, "name": name, "team": team, "mode": mode},
    }
