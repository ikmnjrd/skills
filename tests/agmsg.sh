#!/usr/bin/env bash
set -euo pipefail

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

HOME="$home_dir" "$installed_skill/install.sh" \
  --repo-root "$fixture_repo" \
  --skill-dir "$installed_skill" >/dev/null

runtime_dir="$fixture_repo/.agmsg"
[ "$(cat "$installed_skill/runtime-path")" = "$runtime_dir" ]
[ -f "$runtime_dir/db/messages.db" ]
[ -f "$runtime_dir/config.yaml" ]
[ -d "$runtime_dir/teams" ]
[ -d "$runtime_dir/run" ]
[ ! -e "$installed_skill/db" ]
[ ! -e "$installed_skill/teams" ]
[ ! -e "$installed_skill/run" ]
grep -Fq "$runtime_dir" "$home_dir/.codex/config.toml"
grep -Fq "writable_roots = [\"$runtime_dir\"]" \
  "$home_dir/.codex/config.toml"

before_config="$(sha256sum "$runtime_dir/config.yaml")"
HOME="$home_dir" "$installed_skill/install.sh" \
  --repo-root "$fixture_repo" \
  --skill-dir "$installed_skill" >/dev/null
after_config="$(sha256sum "$runtime_dir/config.yaml")"
[ "$before_config" = "$after_config" ]
[ "$(grep -Fc "$runtime_dir" "$home_dir/.codex/config.toml")" -eq 1 ]

"$installed_skill/scripts/join.sh" alpha alice codex "$project_dir" >/dev/null
identity="$("$installed_skill/scripts/whoami.sh" "$project_dir" codex)"
grep -q '^agent=alice teams=alpha type=codex ' <<<"$identity"

"$installed_skill/scripts/join.sh" alpha bob claude-code "$project_dir" >/dev/null
"$installed_skill/scripts/send.sh" alpha alice bob "ready for review" >/dev/null
inbox="$("$installed_skill/scripts/inbox.sh" alpha bob)"
grep -q 'ready for review' <<<"$inbox"

unread_count="$(sqlite3 "$runtime_dir/db/messages.db" \
  "SELECT count(*) FROM messages WHERE read_at IS NULL;")"
[ "$unread_count" -eq 0 ]

"$installed_skill/scripts/delivery.sh" set turn codex "$project_dir" >/dev/null
codex_hooks="$project_dir/.codex/hooks.json"
grep -Fq "$installed_skill/scripts/check-inbox.sh" "$codex_hooks"
! grep -Fq "$runtime_dir/scripts" "$codex_hooks"

CLAUDE_CODE_SESSION_ID=test-session \
  "$installed_skill/scripts/delivery.sh" set monitor claude-code "$project_dir" \
  >/dev/null
claude_settings="$project_dir/.claude/settings.local.json"
grep -Fq "$installed_skill/scripts/session-start.sh" "$claude_settings"
grep -Fq "$installed_skill/scripts/session-end.sh" "$claude_settings"
! grep -Fq "$runtime_dir/scripts" "$claude_settings"

"$installed_skill/scripts/actas-claim.sh" \
  "$project_dir" claude-code bob test-session >/dev/null
[ -f "$runtime_dir/run/actas.alpha__bob.session" ]

printf 'ok\n'
