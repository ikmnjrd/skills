#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/test-sync-agmsg.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT

make_fixture() {
  local root="$1"
  mkdir -p "$root/scripts" "$root/skills" "$root/bin"
  cp "$REPO_ROOT/scripts/sync-skills.sh" "$root/scripts/"
  cp -R "$REPO_ROOT/skills/agmsg" "$root/skills/agmsg"

  cat > "$root/bin/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [ "$1" = "api" ]; then
  printf '%040d\n' 1
  exit 0
fi

if [ "$1" = "skill" ] && [ "$2" = "install" ]; then
  skill_path="$4"
  shift 4
  agent=""
  scope=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --agent) agent="$2"; shift 2 ;;
      --scope) scope="$2"; shift 2 ;;
      --pin) shift 2 ;;
      --force) shift ;;
      *) shift ;;
    esac
  done

  if [ -n "${SYNC_TEST_PARALLEL_DIR:-}" ]; then
    mkdir -p "$SYNC_TEST_PARALLEL_DIR"
    case "$agent" in
      codex)
        touch "$SYNC_TEST_PARALLEL_DIR/codex-started"
        sleep 1
        touch "$SYNC_TEST_PARALLEL_DIR/codex-finished"
        ;;
      claude-code)
        waited=0
        while [ "$waited" -lt 20 ]; do
          if [ -f "$SYNC_TEST_PARALLEL_DIR/codex-started" ] && \
            [ ! -f "$SYNC_TEST_PARALLEL_DIR/codex-finished" ]; then
            touch "$SYNC_TEST_PARALLEL_DIR/observed"
            break
          fi
          waited=$((waited + 1))
          sleep 0.05
        done
        ;;
    esac
  fi

  [ "$scope" = "user" ]
  case "$agent" in
    codex) target="$HOME/.codex/skills" ;;
    claude-code) target="$HOME/.claude/skills" ;;
    *) exit 1 ;;
  esac

  mkdir -p "$target"
  mkdir -p "$target/agmsg"
  cp -R "$FAKE_SOURCE_ROOT/$skill_path/." "$target/agmsg/"
  exit 0
fi

exit 1
EOF
  chmod +x "$root/bin/gh"
}

success_root="$tmp_dir/success"
make_fixture "$success_root"
success_home="$success_root/home"
mkdir -p \
  "$success_home/.codex/skills/agmsg/scripts" \
  "$success_home/.claude/skills/agmsg/scripts"
touch \
  "$success_home/.codex/skills/agmsg/install.sh" \
  "$success_home/.codex/skills/agmsg/scripts/legacy.sh" \
  "$success_home/.claude/skills/agmsg/install.sh" \
  "$success_home/.claude/skills/agmsg/scripts/legacy.sh"
parallel_dir="$success_root/parallel"
success_output="$(
  cd "$success_root"
  HOME="$success_home" \
  PATH="$success_root/bin:$PATH" \
  FAKE_SOURCE_ROOT="$success_root" \
  SYNC_SKILLS_JOBS=4 \
  SYNC_TEST_PARALLEL_DIR="$parallel_dir" \
  scripts/sync-skills.sh
)"
grep -q '^Result: synchronized$' <<<"$success_output"
[ -f "$parallel_dir/observed" ]
success_physical_root="$(cd "$success_root" && pwd -P)"
runtime_dir="$success_physical_root/.agmsg"
[ "$(cat "$success_home/.codex/skills/agmsg/runtime-path")" = "$runtime_dir" ]
[ "$(cat "$success_home/.claude/skills/agmsg/runtime-path")" = "$runtime_dir" ]
[ -f "$runtime_dir/db/messages.db" ]
[ ! -e "$success_home/.codex/skills/agmsg/install.sh" ]
[ ! -e "$success_home/.codex/skills/agmsg/scripts" ]
[ ! -e "$success_home/.claude/skills/agmsg/install.sh" ]
[ ! -e "$success_home/.claude/skills/agmsg/scripts" ]
# the Python CLI is runnable after sync (no executable bit required)
python3 "$success_home/.codex/skills/agmsg/agmsg.py" whoami "$success_root" codex \
  | grep -q 'not_joined=true'

dry_run_output="$(
  cd "$success_root"
  HOME="$success_home" \
  PATH="$success_root/bin:$PATH" \
  FAKE_SOURCE_ROOT="$success_root" \
  scripts/sync-skills.sh --dry-run
)"
grep -q '^Setup: codex/agmsg$' <<<"$dry_run_output"
grep -q '^Setup: claude-code/agmsg$' <<<"$dry_run_output"

serial_output="$(
  cd "$success_root"
  HOME="$success_home" \
  PATH="$success_root/bin:$PATH" \
  FAKE_SOURCE_ROOT="$success_root" \
  scripts/sync-skills.sh --jobs 1 --agent codex
)"
grep -q '^Result: synchronized$' <<<"$serial_output"
grep -q '^Installed: codex/agmsg$' <<<"$serial_output"

failure_root="$tmp_dir/failure"
make_fixture "$failure_root"
failure_home="$failure_root/home"
mkdir -p "$failure_home"
printf 'import sys\nsys.exit(1)\n' > "$failure_root/skills/agmsg/agmsg.py"
set +e
failure_output="$(
  cd "$failure_root"
  HOME="$failure_home" \
  PATH="$failure_root/bin:$PATH" \
  FAKE_SOURCE_ROOT="$failure_root" \
  scripts/sync-skills.sh
)"
failure_status="$?"
set -e
[ "$failure_status" -eq 1 ]
grep -q '^Result: failed$' <<<"$failure_output"
grep -q '^Setup failed: codex/agmsg$' <<<"$failure_output"
grep -q '^Setup failed: claude-code/agmsg$' <<<"$failure_output"

printf 'ok\n'
