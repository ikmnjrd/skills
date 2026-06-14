"""Team membership + identity registry (JSON under ``teams/<team>/config.json``).

Mirrors the semantics of the former whoami/join/leave/identities/team/rename/
rename-team/reset shell scripts, in plain Python dict manipulation.

config.json shape::

    {"name": "<team>", "agents": {"<id>": {"registrations": [
        {"type": "<agent_type>", "project": "<path>"}]}}, "created_at": "<utc>"}
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import locking, storage
from . import platform as plat
from .envelope import AgmsgError
from .jsonio import atomic_write_json


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _team_config(team: str) -> Path:
    return plat.teams_dir() / team / "config.json"


def _load(path: Path) -> Optional[dict]:
    """Load a team config. Missing -> None. A present-but-corrupt file (read
    error, invalid JSON, or non-object root) is a hard error so mutations never
    silently overwrite it."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgmsgError("team_read_error", f"cannot read team file {path}: {exc}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AgmsgError(
            "team_parse_error",
            f"team file {path} is not valid JSON; refusing to modify it ({exc}).",
        )
    if not isinstance(data, dict):
        raise AgmsgError(
            "team_type_error",
            f"team file {path} must be a JSON object, got {type(data).__name__}.",
        )
    return data


def _save(path: Path, data: dict) -> None:
    atomic_write_json(path, data, error_code="team_write_error")


def _registrations(entry: dict) -> list[dict]:
    """Normalize legacy single-registration shape -> list."""
    regs = entry.get("registrations")
    if isinstance(regs, list):
        return regs
    if "type" in entry or "project" in entry:
        return [{"type": entry.get("type"), "project": entry.get("project")}]
    return []


def _iter_team_dirs() -> list[Path]:
    teams = plat.teams_dir()
    if not teams.is_dir():
        return []
    return sorted(p for p in teams.iterdir() if (p / "config.json").is_file())


# --------------------------------------------------------------------------- #
# join / leave


def join(team: str, agent: str, agent_type: str, project: str) -> dict:
    plat.require_agent_type(agent_type)
    path = _team_config(team)
    lines = []
    config = _load(path)
    created = False
    if config is None:
        config = {"name": team, "agents": {}, "created_at": _now()}
        created = True
        lines.append(f"Created team: {team}")

    agents = config.setdefault("agents", {})
    entry = agents.get(agent)
    reg = {"type": agent_type, "project": project}
    if entry is None:
        agents[agent] = {"registrations": [reg]}
    else:
        regs = _registrations(entry)
        if not any(
            r.get("type") == agent_type and r.get("project") == project
            for r in regs
        ):
            regs.append(reg)
        agents[agent] = {"registrations": regs}

    _save(path, config)
    lines.append(f"Joined team {team} as {agent}")
    return {
        "human": "\n".join(lines),
        "data": {"team": team, "agent": agent, "created": created},
    }


def leave(team: str, agent: str) -> dict:
    path = _team_config(team)
    config = _load(path)
    if config is None:
        raise AgmsgError("team_not_found", f"Team not found: {team}")
    agents = config.get("agents", {})
    if agent not in agents:
        raise AgmsgError(
            "agent_not_in_team", f"Agent {agent} not in team {team}"
        )
    del agents[agent]
    if not agents:
        try:
            path.unlink()
            path.parent.rmdir()
        except OSError:
            pass
        return {
            "human": f"Left team {team} (team removed — no members left)",
            "data": {"team": team, "agent": agent, "team_removed": True},
        }
    _save(path, config)
    return {
        "human": f"Left team {team}",
        "data": {"team": team, "agent": agent, "team_removed": False},
    }


# --------------------------------------------------------------------------- #
# identities / whoami


def identities(project: str, agent_type: str) -> list[tuple[str, str]]:
    """Distinct (team, agent) pairs registered for exactly (project, type)."""
    pairs: list[tuple[str, str]] = []
    for team_dir in _iter_team_dirs():
        config = _load(team_dir / "config.json")
        if not config:
            continue
        name = config.get("name")
        if not name:
            continue
        for agent, entry in config.get("agents", {}).items():
            for reg in _registrations(entry):
                if reg.get("project") == project and reg.get("type") == agent_type:
                    pairs.append((name, agent))
                    break
    seen = set()
    distinct = []
    for pair in sorted(pairs):
        if pair not in seen:
            seen.add(pair)
            distinct.append(pair)
    return distinct


def _dedup(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def whoami(project: str, agent_type: str) -> dict:
    teams = plat.teams_dir()
    if not teams.is_dir():
        return {
            "human": "not_joined=true available_teams=none",
            "data": {"status": "not_joined", "available_teams": []},
        }

    exact = identities(project, agent_type)
    all_teams: list[str] = []
    suggested: list[tuple[str, str]] = []
    for team_dir in _iter_team_dirs():
        config = _load(team_dir / "config.json")
        if not config:
            continue
        name = config.get("name")
        if name:
            all_teams.append(name)
        for agent, entry in config.get("agents", {}).items():
            if any(r.get("type") == agent_type for r in _registrations(entry)):
                if name:
                    suggested.append((name, agent))

    all_teams = _dedup(all_teams)
    avail = ",".join(all_teams) if all_teams else "none"

    if not exact and not suggested:
        return {
            "human": f"not_joined=true available_teams={avail}",
            "data": {"status": "not_joined", "available_teams": all_teams},
        }

    if not exact:
        agents = _dedup([a for _, a in suggested])
        s_teams = _dedup([t for t, _ in suggested])
        human = (
            f"suggest=true agents={','.join(agents)} teams={','.join(s_teams)} "
            f"type={agent_type} project={project} available_teams={avail}"
        )
        return {
            "human": human,
            "data": {
                "status": "suggest",
                "agents": agents,
                "teams": s_teams,
                "type": agent_type,
                "project": project,
                "available_teams": all_teams,
            },
        }

    agents = _dedup([a for _, a in exact])
    e_teams = _dedup([t for t, _ in exact])
    if len(agents) == 1:
        human = (
            f"agent={agents[0]} teams={','.join(e_teams)} "
            f"type={agent_type} project={project}"
        )
        return {
            "human": human,
            "data": {
                "status": "agent",
                "agent": agents[0],
                "teams": e_teams,
                "type": agent_type,
                "project": project,
            },
        }
    human = (
        f"multiple=true agents={','.join(agents)} teams={','.join(e_teams)} "
        f"type={agent_type} project={project}"
    )
    return {
        "human": human,
        "data": {
            "status": "multiple",
            "agents": agents,
            "teams": e_teams,
            "type": agent_type,
            "project": project,
        },
    }


# --------------------------------------------------------------------------- #
# team / rename / rename-team / reset


def team_info(team: str) -> dict:
    config = _load(_team_config(team))
    if config is None:
        raise AgmsgError("team_not_found", f"Team not found: {team}")
    lines = [f"Team: {team}", ""]
    members = []
    for agent, entry in config.get("agents", {}).items():
        regs = _registrations(entry)
        types = _dedup([r.get("type") for r in regs if r.get("type")])
        project = regs[-1].get("project") if regs else "?"
        if project is None:
            project = "?"
        count = len(regs)
        type_str = ",".join(types)
        if count > 1:
            lines.append(
                f"  {agent} ({type_str}) — {project} (+{count - 1} more)"
            )
        else:
            lines.append(f"  {agent} ({type_str}) — {project}")
        members.append(
            {"agent": agent, "types": types, "project": project, "registrations": count}
        )
    lines.append("")
    lines.append(f"{len(members)} member(s)")
    return {"human": "\n".join(lines), "data": {"team": team, "members": members}}


def rename(team: str, old: str, new: str) -> dict:
    path = _team_config(team)
    config = _load(path)
    if config is None:
        raise AgmsgError("team_not_found", f"Team not found: {team}")
    agents = config.get("agents", {})
    if old not in agents:
        raise AgmsgError("agent_not_in_team", f"Agent {old} not in team {team}")
    if new in agents and agents.get(new) is not None:
        raise AgmsgError(
            "agent_exists", f"Agent {new} already exists in team {team}"
        )
    agents[new] = agents.pop(old)
    _save(path, config)
    storage.rename_agent(team, old, new)
    return {
        "human": f"Renamed {old} → {new} in team {team}",
        "data": {"team": team, "old": old, "new": new},
    }


def rename_team(old: str, new: str) -> dict:
    if old == new:
        raise AgmsgError(
            "same_name", f"Old and new team names are the same: {old}"
        )
    old_dir = plat.teams_dir() / old
    new_dir = plat.teams_dir() / new
    if not old_dir.is_dir():
        raise AgmsgError("team_not_found", f"Team not found: {old}")
    if new_dir.exists():
        raise AgmsgError("team_exists", f"Team already exists: {new}")
    shutil.move(str(old_dir), str(new_dir))
    config = _load(new_dir / "config.json")
    if config is not None:
        config["name"] = new
        _save(new_dir / "config.json", config)
    storage.rename_team(old, new)
    human = (
        f"Renamed team {old} → {new}\n\n"
        "Note: existing members in other projects/sessions still see the old\n"
        "team name cached. Each member should re-run whoami in their project\n"
        "to pick up the new name."
    )
    return {"human": human, "data": {"old": old, "new": new}}


def reset(
    project: str,
    agent_type: str,
    agent: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    if not agent:
        info = whoami(project, agent_type)
        status = info["data"]["status"]
        if status == "agent":
            agent = info["data"]["agent"]
        elif status == "multiple":
            raise AgmsgError(
                "ambiguous_identity",
                "Multiple identities match this project/type. "
                "Pass an agent_id explicitly.",
            )
        else:
            raise AgmsgError(
                "no_identity",
                "No registered identity found for this project/type.",
            )

    if not plat.teams_dir().is_dir():
        return {
            "human": "No team registrations found.",
            "data": {"removed": 0, "teams": 0},
        }

    lines = []
    removed = 0
    touched = 0
    for team_dir in _iter_team_dirs():
        team_name = team_dir.name
        path = team_dir / "config.json"
        config = _load(path)
        if not config:
            continue
        agents = config.get("agents", {})
        entry = agents.get(agent)
        if entry is None:
            continue
        regs = _registrations(entry)
        match = [
            r
            for r in regs
            if r.get("type") == agent_type and r.get("project") == project
        ]
        if not match:
            continue
        remaining = [
            r
            for r in regs
            if not (r.get("type") == agent_type and r.get("project") == project)
        ]
        if remaining:
            agents[agent] = {"registrations": remaining}
        else:
            del agents[agent]
        if not agents:
            try:
                path.unlink()
                path.parent.rmdir()
            except OSError:
                pass
        else:
            _save(path, config)
        removed += len(match)
        touched += 1
        lines.append(
            f"Cleared {len(match)} registration(s) for {agent} from {team_name}"
        )
        if session_id:
            locking.release(team_name, agent, session_id)

    if removed == 0:
        lines.append("No registrations removed.")
    else:
        lines.append(
            f"Reset complete: removed {removed} registration(s) "
            f"across {touched} team(s)"
        )
    return {
        "human": "\n".join(lines),
        "data": {"agent": agent, "removed": removed, "teams": touched},
    }
