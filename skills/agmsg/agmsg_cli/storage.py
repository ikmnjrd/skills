"""SQLite message store (``messages.db``).

Schema is unchanged from the shell implementation (WAL mode), so an existing
database keeps working. The raw message body is stored verbatim; render-time
escaping is the caller's concern.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from . import platform as plat

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team TEXT NOT NULL,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  read_at TEXT
);

CREATE INDEX idx_unread ON messages(team, to_agent, read_at) WHERE read_at IS NULL;
CREATE INDEX idx_history ON messages(team, created_at DESC);
"""


def init_db(path: Optional[Path] = None) -> bool:
    """Create the database if absent. Returns True if it was created."""
    path = path or plat.db_path()
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return True


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(plat.db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def db_exists() -> bool:
    return plat.db_path().exists()


def ensure_db() -> None:
    init_db()


def send(team: str, from_agent: str, to_agent: str, body: str) -> int:
    ensure_db()
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO messages (team, from_agent, to_agent, body) "
            "VALUES (?, ?, ?, ?)",
            (team, from_agent, to_agent, body),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def unread(team: str, agent: str) -> list[sqlite3.Row]:
    """Unread messages addressed to agent in team, oldest first."""
    if not db_exists():
        return []
    conn = _connect()
    try:
        return list(
            conn.execute(
                "SELECT from_agent, body, created_at FROM messages "
                "WHERE team=? AND to_agent=? AND read_at IS NULL "
                "ORDER BY created_at ASC",
                (team, agent),
            )
        )
    finally:
        conn.close()


def mark_read(team: str, agent: str) -> None:
    """Mark all currently-unread messages for (team, agent) as read."""
    if not db_exists():
        return
    conn = _connect()
    try:
        conn.execute(
            "UPDATE messages SET "
            "read_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
            "WHERE team=? AND to_agent=? AND read_at IS NULL",
            (team, agent),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def history(team: str, agent: Optional[str], limit: int) -> list[sqlite3.Row]:
    """Most recent <limit> messages, returned oldest-first for display."""
    if not db_exists():
        return []
    conn = _connect()
    try:
        if agent:
            rows = list(
                conn.execute(
                    "SELECT from_agent, to_agent, body, created_at, read_at "
                    "FROM messages WHERE team=? AND (from_agent=? OR to_agent=?) "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (team, agent, agent, limit),
                )
            )
        else:
            rows = list(
                conn.execute(
                    "SELECT from_agent, to_agent, body, created_at, read_at "
                    "FROM messages WHERE team=? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (team, limit),
                )
            )
        rows.reverse()
        return rows
    finally:
        conn.close()


def _pairs_clause(pairs: Iterable[tuple[str, str]]) -> tuple[str, list[str]]:
    clauses = []
    params: list[str] = []
    for team, agent in pairs:
        clauses.append("(team=? AND to_agent=?)")
        params.extend([team, agent])
    return " OR ".join(clauses), params


def max_id(pairs: list[tuple[str, str]]) -> int:
    if not db_exists() or not pairs:
        return 0
    clause, params = _pairs_clause(pairs)
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT COALESCE(MAX(id), 0) FROM messages WHERE {clause}", params
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def poll(last_id: int, pairs: list[tuple[str, str]]) -> list[sqlite3.Row]:
    if not db_exists() or not pairs:
        return []
    clause, params = _pairs_clause(pairs)
    conn = _connect()
    try:
        return list(
            conn.execute(
                "SELECT id, created_at, team, from_agent, to_agent, body "
                f"FROM messages WHERE id > ? AND ({clause}) ORDER BY id",
                [last_id, *params],
            )
        )
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def rename_agent(team: str, old: str, new: str) -> None:
    if not db_exists():
        return
    conn = _connect()
    try:
        conn.execute(
            "UPDATE messages SET from_agent=? WHERE team=? AND from_agent=?",
            (new, team, old),
        )
        conn.execute(
            "UPDATE messages SET to_agent=? WHERE team=? AND to_agent=?",
            (new, team, old),
        )
        conn.commit()
    finally:
        conn.close()


def rename_team(old: str, new: str) -> None:
    if not db_exists():
        return
    conn = _connect()
    try:
        conn.execute(
            "UPDATE messages SET team=? WHERE team=?", (new, old)
        )
        conn.commit()
    finally:
        conn.close()
