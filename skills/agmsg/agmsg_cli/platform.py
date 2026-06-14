"""Path resolution, runtime binding, OS detection, and agent-type detection.

Centralizes runtime/storage path resolution and the agent-runtime detection
used across the CLI.
"""
from __future__ import annotations

import os
import platform as _platform
import subprocess
import sys
from pathlib import Path

from . import AGENT_TYPES
from .envelope import AgmsgError


def skill_dir() -> Path:
    """The installed skill root (the directory holding ``agmsg.py``)."""
    return Path(__file__).resolve().parents[1]


def runtime_path_file() -> Path:
    return skill_dir() / "runtime-path"


def python_path_file() -> Path:
    return skill_dir() / "python-path"


def runtime_dir() -> Path:
    """Resolve the runtime state directory (``<repo>/.agmsg``).

    Order: ``AGMSG_RUNTIME_DIR`` env override, else the path recorded in
    ``<skill>/runtime-path`` (which must exist and be a directory).
    """
    env = os.environ.get("AGMSG_RUNTIME_DIR")
    if env:
        return Path(env.rstrip("/"))

    rp = runtime_path_file()
    if not rp.is_file():
        raise AgmsgError(
            "not_initialized",
            f"agmsg is not initialized: missing {rp}. "
            f"Run: python3 {skill_dir() / 'agmsg.py'} install",
        )
    line = rp.read_text(encoding="utf-8").splitlines()[0:1]
    value = line[0].strip() if line else ""
    rd = Path(value)
    if not value or not rd.is_dir():
        raise AgmsgError(
            "runtime_unavailable",
            f"agmsg runtime is unavailable: {value}. "
            f"Re-run install after moving the skills repository.",
        )
    return rd


def teams_dir() -> Path:
    return runtime_dir() / "teams"


def run_dir() -> Path:
    return runtime_dir() / "run"


def config_path() -> Path:
    return runtime_dir() / "config.json"


def storage_dir() -> Path:
    env = os.environ.get("AGMSG_STORAGE_PATH")
    if env:
        return Path(env.rstrip("/"))
    return runtime_dir() / "db"


def db_path() -> Path:
    return storage_dir() / "messages.db"


def python_executable() -> str:
    """Absolute path to the Python interpreter recorded at install time.

    Hooks must use a stable absolute interpreter path; fall back to the
    current interpreter when the install marker is absent.
    """
    pf = python_path_file()
    if pf.is_file():
        recorded = pf.read_text(encoding="utf-8").strip()
        if recorded:
            return recorded
    return sys.executable or "python3"


def agmsg_py() -> Path:
    return skill_dir() / "agmsg.py"


def os_name() -> str:
    system = _platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    return system.lower()


def _proc_comm(pid: int) -> str:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            check=False,
        )
        return os.path.basename(out.stdout.strip())
    except Exception:
        return ""


def _proc_ppid(pid: int) -> int:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "ppid="],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(out.stdout.strip() or "0")
    except Exception:
        return 0


def detect_agent_type() -> str:
    """Best-effort detection of the calling agent runtime.

    Only ``claude-code`` and ``codex`` are supported. Env markers win; then a
    bounded walk up the process tree; default ``claude-code``.
    """
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude-code"
    if os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_THREAD_ID"):
        return "codex"

    pid = os.getpid()
    for _ in range(10):
        if pid <= 1:
            break
        name = _proc_comm(pid)
        if name == "codex" or name.startswith("codex-"):
            return "codex"
        if name in ("claude", "claude-code") or name.startswith("claude-"):
            return "claude-code"
        pid = _proc_ppid(pid)

    return "claude-code"


def require_agent_type(value: str) -> str:
    if value not in AGENT_TYPES:
        raise AgmsgError(
            "bad_agent_type",
            f"Unknown agent type: '{value}' "
            f"(supported: {', '.join(AGENT_TYPES)})",
        )
    return value
