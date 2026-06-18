#!/usr/bin/env bash
set -euo pipefail

# Acceptance test for the Python agmsg CLI. Shell-driven (the outer harness
# stays shell) but exercises `python3 agmsg.py <command>`.

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/test-agmsg.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT

fixture_repo="$tmp_dir/repo"
installed_skill="$tmp_dir/installed/agmsg"
home_dir="$tmp_dir/home"
project_dir="$tmp_dir/project"

mkdir -p "$fixture_repo/skills" "$tmp_dir/installed" "$home_dir" "$project_dir"
cp -R "$REPO_ROOT/skills/agmsg" "$fixture_repo/skills/agmsg"
cp -R "$REPO_ROOT/skills/agmsg" "$installed_skill"
mkdir -p "$home_dir/.codex"
printf '[sandbox_workspace_write]\nwritable_roots = []\n' \
  > "$home_dir/.codex/config.toml"

agmsg() { python3 "$installed_skill/agmsg.py" "$@"; }

HOME="$home_dir" agmsg install \
  --repo-root "$fixture_repo" \
  --skill-dir "$installed_skill" >/dev/null

runtime_dir="$fixture_repo/.agmsg"
[ "$(cat "$installed_skill/runtime-path")" = "$runtime_dir" ]
[ -f "$installed_skill/python-path" ]
[ -f "$runtime_dir/db/messages.db" ]
[ -f "$runtime_dir/config.json" ]
[ -d "$runtime_dir/teams" ]
[ -d "$runtime_dir/run" ]
[ ! -e "$installed_skill/db" ]
[ ! -e "$installed_skill/teams" ]
[ ! -e "$installed_skill/run" ]
grep -Fq "$runtime_dir" "$home_dir/.codex/config.toml"
grep -Fq "writable_roots = [\"$runtime_dir\"]" \
  "$home_dir/.codex/config.toml"

# install is idempotent
before_config="$(sha256sum "$runtime_dir/config.json")"
HOME="$home_dir" agmsg install \
  --repo-root "$fixture_repo" \
  --skill-dir "$installed_skill" >/dev/null
after_config="$(sha256sum "$runtime_dir/config.json")"
[ "$before_config" = "$after_config" ]
[ "$(grep -Fc "$runtime_dir" "$home_dir/.codex/config.toml")" -eq 1 ]

# identity + messaging
agmsg join alpha alice codex "$project_dir" >/dev/null
identity="$(agmsg whoami "$project_dir" codex)"
grep -q '^agent=alice teams=alpha type=codex ' <<<"$identity"

agmsg join alpha bob claude-code "$project_dir" >/dev/null
agmsg send alpha alice bob "ready for review" >/dev/null
inbox="$(agmsg inbox alpha bob)"
grep -q 'ready for review' <<<"$inbox"

unread_count="$(sqlite3 "$runtime_dir/db/messages.db" \
  "SELECT count(*) FROM messages WHERE read_at IS NULL;")"
[ "$unread_count" -eq 0 ]

# delivery: codex turn -> .codex/hooks.json invokes agmsg.py check-inbox
agmsg delivery set turn codex "$project_dir" >/dev/null
codex_hooks="$project_dir/.codex/hooks.json"
grep -Fq "$installed_skill/agmsg.py" "$codex_hooks"
grep -Fq "check-inbox" "$codex_hooks"
! grep -Fq "$runtime_dir" "$codex_hooks"

# delivery: claude-code monitor -> settings.local.json session-start/session-end
CLAUDE_CODE_SESSION_ID=test-session \
  agmsg delivery set monitor claude-code "$project_dir" >/dev/null
claude_settings="$project_dir/.claude/settings.local.json"
grep -Fq "session-start" "$claude_settings"
grep -Fq "session-end" "$claude_settings"
! grep -Fq "$runtime_dir" "$claude_settings"

# delivery: codex monitor installs SessionStart/SessionEnd and a Python shim
HOME="$home_dir" agmsg delivery set monitor codex "$project_dir" >/dev/null
grep -Fq "session-start" "$codex_hooks"
grep -Fq "session-end" "$codex_hooks"
[ -x "$home_dir/.agents/bin/codex" ]
grep -Fq "Optional Codex entrypoint shim for agmsg monitor mode" \
  "$home_dir/.agents/bin/codex"
grep -Fq "'codex-shim'" "$home_dir/.agents/bin/codex"

# codex bridge beta deliberately rejects both mode
if agmsg delivery set both codex "$project_dir" >/dev/null 2>&1; then
  echo "expected codex both mode to be rejected" >&2
  exit 1
fi

# actas claims a per-(team, agent) lock
CLAUDE_CODE_SESSION_ID=test-session \
  agmsg actas bob --project "$project_dir" --type claude-code >/dev/null
[ -f "$runtime_dir/run/actas.alpha__bob.session" ]

# old (shell-era) runtime is rejected without --reset
touch "$runtime_dir/config.yaml"
rm "$runtime_dir/config.json"
if HOME="$home_dir" agmsg install \
  --repo-root "$fixture_repo" --skill-dir "$installed_skill" >/dev/null 2>&1; then
  echo "expected old-runtime install to fail" >&2
  exit 1
fi
HOME="$home_dir" agmsg install --reset \
  --repo-root "$fixture_repo" --skill-dir "$installed_skill" >/dev/null
[ -f "$runtime_dir/config.json" ]

printf 'ok\n'
