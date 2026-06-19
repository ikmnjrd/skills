"""``agmsg.py install`` — initialize runtime state and bind this skill copy.

Writes ``runtime-path`` (the ``<repo>/.agmsg`` dir) and ``python-path`` (the
absolute interpreter, used in generated hooks), initializes the SQLite store
and JSON config, and registers the runtime dir in Codex's sandbox writable
roots. An existing *old* (shell-era) ``.agmsg`` is never auto-migrated: it is
an error unless ``--reset`` is given (which backs it up and re-initializes).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path

from . import config, storage
from . import platform as plat
from .envelope import AgmsgError

USAGE = (
    "Usage: agmsg.py install [--repo-root PATH] [--skill-dir PATH] [--reset]\n\n"
    "Initialize agmsg runtime state and bind this installed skill copy to it."
)


def _is_skills_repo(path: Path) -> bool:
    return (path / "skills" / "agmsg" / "SKILL.md").is_file()


def _detect_repo_root(explicit: str | None, skill_dir: Path) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("AGMSG_REPO_ROOT")
    if env:
        return Path(env)
    home = os.environ.get("HOME")
    if home and _is_skills_repo(Path(home) / "workspace" / "skills"):
        return Path(home) / "workspace" / "skills"
    candidate = skill_dir
    while str(candidate) != candidate.anchor:
        if _is_skills_repo(candidate):
            return candidate
        candidate = candidate.parent
    raise AgmsgError(
        "no_repo",
        "Could not locate the skills repository. "
        "Set AGMSG_REPO_ROOT or pass --repo-root <path>.",
    )


def _looks_like_old_runtime(runtime: Path) -> bool:
    """A shell-era runtime has config.yaml and no JSON config."""
    return (runtime / "config.yaml").is_file() and not (
        runtime / "config.json"
    ).is_file()


def _quote_toml_string(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ensure_writable_roots(toml: Path, roots: list[Path]) -> None:
    text = toml.read_text(encoding="utf-8")
    missing = [root for root in roots if str(root) not in text]
    if not missing:
        return

    shutil.copyfile(toml, str(toml) + ".bak")
    entries = [_quote_toml_string(root) for root in missing]

    lines = text.splitlines()
    wr_idx = next(
        (i for i, ln in enumerate(lines) if re.match(r"^\s*writable_roots\s*=", ln)),
        None,
    )
    if wr_idx is not None:
        # Find the closing ']' (single- or multi-line array).
        close_idx = next(
            (j for j in range(wr_idx, len(lines)) if "]" in lines[j]), wr_idx
        )
        has_value = any('"' in lines[j] for j in range(wr_idx, close_idx + 1))
        repl = (
            ", " + ", ".join(entries) + "]"
            if has_value
            else ", ".join(entries) + "]"
        )
        lines[close_idx] = lines[close_idx].replace("]", repl, 1)
        toml.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    hdr_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "[sandbox_workspace_write]"),
        None,
    )
    if hdr_idx is not None:
        lines.insert(hdr_idx + 1, f"writable_roots = [{', '.join(entries)}]")
        toml.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    with toml.open("a", encoding="utf-8") as fh:
        fh.write(
            "\n[sandbox_workspace_write]\n"
            f"writable_roots = [{', '.join(entries)}]\n"
        )


def configure_codex(runtime_dir: Path) -> None:
    home = os.environ.get("HOME")
    if not home:
        return
    config_dir = Path(home) / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "sessions").mkdir(parents=True, exist_ok=True)
    toml = config_dir / "config.toml"
    if not toml.exists():
        toml.write_text("", encoding="utf-8")

    _ensure_writable_roots(toml, [runtime_dir, config_dir / "sessions"])


def run(args: list[str]) -> dict:
    repo_root_arg = None
    skill_dir_arg = None
    reset = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--repo-root":
            if i + 1 >= len(args):
                raise AgmsgError("bad_args", "--repo-root requires a path", 2)
            repo_root_arg = args[i + 1]
            i += 2
        elif arg == "--skill-dir":
            if i + 1 >= len(args):
                raise AgmsgError("bad_args", "--skill-dir requires a path", 2)
            skill_dir_arg = args[i + 1]
            i += 2
        elif arg == "--reset":
            reset = True
            i += 1
        elif arg in ("-h", "--help"):
            return {"human": USAGE, "data": {"help": True}}
        else:
            raise AgmsgError("bad_args", f"Unknown option: {arg}", 2)

    skill_dir = (
        Path(skill_dir_arg).resolve() if skill_dir_arg else plat.skill_dir()
    )
    repo_root = _detect_repo_root(repo_root_arg, skill_dir).resolve()

    if not _is_skills_repo(repo_root):
        raise AgmsgError(
            "bad_repo", f"Not a skills repository containing skills/agmsg: {repo_root}"
        )
    if not (skill_dir / "SKILL.md").is_file() or not (
        skill_dir / "agmsg.py"
    ).is_file():
        raise AgmsgError("bad_skill", f"Not an agmsg skill directory: {skill_dir}")

    runtime_dir = repo_root / ".agmsg"

    if runtime_dir.exists() and _looks_like_old_runtime(runtime_dir):
        if not reset:
            raise AgmsgError(
                "old_runtime",
                f"An old (shell-era) runtime was found at {runtime_dir}. "
                "It is not auto-migrated. Re-run with --reset to back it up "
                "and re-initialize.",
            )

    backed_up = None
    if reset and runtime_dir.exists():
        backup = runtime_dir.with_name(f".agmsg.bak.{int(time.time())}")
        shutil.move(str(runtime_dir), str(backup))
        backed_up = str(backup)

    for sub in ("db", "teams", "run"):
        (runtime_dir / sub).mkdir(parents=True, exist_ok=True)

    (skill_dir / "runtime-path").write_text(
        str(runtime_dir) + "\n", encoding="utf-8"
    )
    (skill_dir / "python-path").write_text(
        (sys.executable or "python3") + "\n", encoding="utf-8"
    )

    os.environ["AGMSG_RUNTIME_DIR"] = str(runtime_dir)
    storage.init_db(runtime_dir / "db" / "messages.db")
    config.ensure_exists()
    configure_codex(runtime_dir)

    human = (
        "agmsg initialized\n"
        f"runtime: {runtime_dir}\n"
        f"skill: {skill_dir}"
    )
    if backed_up:
        human += f"\nbacked up previous runtime to: {backed_up}"
    return {
        "human": human,
        "data": {
            "runtime": str(runtime_dir),
            "skill": str(skill_dir),
            "python": sys.executable,
            "backed_up": backed_up,
        },
    }
