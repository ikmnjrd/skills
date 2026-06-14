"""Per-(team, agent) exclusivity locks for the ``actas`` role model.

A filesystem ownership protocol identical in semantics to the previous
``lib/actas-lock.sh``:

  Lock file: <run>/actas.<enc(team)>__<enc(agent)>.session  (content: owner sid)
  Liveness:  a sid is alive iff some <run>/cc-instance.<pid> contains it and
             that pid is alive.

Atomic claim uses ``os.link`` of a per-call temp file (POSIX-atomic).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import platform as plat

_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)


def _encode(name: str) -> str:
    out = []
    for byte in name.encode("utf-8"):
        ch = chr(byte)
        if ch in _SAFE:
            out.append(ch)
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def _run_dir() -> Path:
    return plat.run_dir()


def lock_path(team: str, agent: str) -> Path:
    return _run_dir() / f"actas.{_encode(team)}__{_encode(agent)}.session"


def lock_owner(team: str, agent: str) -> str:
    path = lock_path(team, agent)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def sid_alive(sid: str) -> bool:
    if not sid:
        return False
    run = _run_dir()
    if not run.is_dir():
        return False
    for entry in run.glob("cc-instance.*"):
        suffix = entry.name.rsplit(".", 1)[-1]
        if not suffix.isdigit():
            continue
        if not _pid_alive(int(suffix)):
            continue
        try:
            if entry.read_text(encoding="utf-8").strip() == sid:
                return True
        except OSError:
            continue
    return False


def _try_claim(team: str, agent: str, sid: str) -> str:
    lock = lock_path(team, agent)
    run = _run_dir()
    run.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".actas-claim.", dir=str(run))
    try:
        os.write(fd, (sid + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.link(tmp, str(lock))
        os.unlink(tmp)
        return "ok"
    except FileExistsError:
        os.unlink(tmp)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return "error"

    existing = lock_owner(team, agent)
    if existing == sid:
        return "ok"
    if not existing or not sid_alive(existing):
        return "stale"
    return f"held:{existing}"


def claim(team: str, agent: str, sid: str) -> str:
    """Claim (team, agent) for sid. Returns "ok" or "held:<other_sid>"."""
    lock = lock_path(team, agent)
    reclaim = Path(str(lock) + ".reclaim.d")
    for _ in range(3):
        result = _try_claim(team, agent, sid)
        if result == "ok":
            return "ok"
        if result.startswith("held:"):
            return result
        if result == "stale":
            try:
                reclaim.mkdir()
            except FileExistsError:
                continue
            except OSError:
                continue
            try:
                owner = lock_owner(team, agent)
                if not owner or not sid_alive(owner):
                    try:
                        lock.unlink()
                    except OSError:
                        pass
            finally:
                try:
                    reclaim.rmdir()
                except OSError:
                    pass
            continue
        return result  # error
    return "held:"


def release(team: str, agent: str, sid: str) -> None:
    lock = lock_path(team, agent)
    if not lock.is_file():
        return
    if lock_owner(team, agent) == sid:
        try:
            lock.unlink()
        except OSError:
            pass


def release_all(sid: str) -> None:
    run = _run_dir()
    if not run.is_dir():
        return
    for entry in run.glob("actas.*.session"):
        try:
            owner = entry.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            continue
        if owner == sid:
            try:
                entry.unlink()
            except OSError:
                pass


def gc_stale() -> int:
    run = _run_dir()
    if not run.is_dir():
        return 0
    count = 0
    for entry in run.glob("actas.*.session"):
        try:
            owner = entry.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            owner = ""
        if not owner or not sid_alive(owner):
            try:
                entry.unlink()
                count += 1
            except OSError:
                pass
    return count


def state(team: str, agent: str, sid: str) -> str:
    """Classify the lock: 'free' | 'mine' | 'other:<owner_sid>'."""
    owner = lock_owner(team, agent)
    if not owner:
        return "free"
    if owner == sid:
        return "mine"
    if sid_alive(owner):
        return f"other:{owner}"
    return "free"
