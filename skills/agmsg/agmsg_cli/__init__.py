"""agmsg — agent-to-agent messaging CLI (Python implementation).

A single Python entry point (``agmsg.py``) backed by this package replaces the
previous shell script set. Messages live in SQLite; configuration and team
registration live in JSON. See SKILL.md for the user-facing contract.
"""

SCHEMA_VERSION = 1
AGENT_TYPES = ("claude-code", "codex")
