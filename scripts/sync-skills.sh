#!/usr/bin/env bash
set -u

SOURCE_REPO="ikmnjrd/skills"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INVOCATION_DIR="$PWD"

scope="user"
dry_run=false
agents=("codex" "claude-code")
agent_option_seen=false
activity_pid=""
activity_active=false
activity_tty=false
tmp_dir=""

usage() {
  cat <<'EOF'
Usage: scripts/sync-skills.sh [options]

Synchronize installed skills with this repository's skills/ directory.

Options:
  --agent AGENT   Target agent: codex or claude-code. May be repeated.
  --scope SCOPE   Installation scope: user or project. Default: user.
  --dry-run       Show the changes without installing or removing skills.
  -h, --help      Show this help.
EOF
}

fail_usage() {
  printf 'Error: %s\n\n' "$1" >&2
  usage >&2
  exit 2
}

start_activity() {
  activity_active=true

  if [ -t 2 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    activity_tty=true
    (
      local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
      local frame
      while true; do
        for frame in "${frames[@]}"; do
          printf '\r\033[2K%s  Syncing skills with GitHub...' "$frame" >&2
          sleep 0.12
        done
      done
    ) &
    activity_pid="$!"
  else
    printf 'Syncing skills with GitHub...\n' >&2
  fi
}

stop_activity() {
  local outcome="${1:-success}"

  [ "$activity_active" = true ] || return

  if [ -n "$activity_pid" ]; then
    kill "$activity_pid" 2>/dev/null || true
    wait "$activity_pid" 2>/dev/null || true
    activity_pid=""
  fi

  if [ "$activity_tty" = true ]; then
    printf '\r\033[2K' >&2
  fi

  if [ "$outcome" = "success" ]; then
    printf '✓ GitHub sync finished.\n' >&2
  else
    printf '× GitHub sync stopped.\n' >&2
  fi

  activity_active=false
}

cleanup() {
  stop_activity failure
  if [ -n "$tmp_dir" ]; then
    rm -rf -- "$tmp_dir"
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

add_agent() {
  local candidate="$1"
  local existing

  case "$candidate" in
    codex|claude-code) ;;
    *) fail_usage "unsupported agent: $candidate" ;;
  esac

  if [ "$agent_option_seen" = false ]; then
    agents=()
    agent_option_seen=true
  fi

  for existing in "${agents[@]}"; do
    [ "$existing" = "$candidate" ] && return
  done
  agents+=("$candidate")
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --agent)
      [ "$#" -ge 2 ] || fail_usage "--agent requires a value"
      add_agent "$2"
      shift 2
      ;;
    --agent=*)
      add_agent "${1#*=}"
      shift
      ;;
    --scope)
      [ "$#" -ge 2 ] || fail_usage "--scope requires a value"
      scope="$2"
      shift 2
      ;;
    --scope=*)
      scope="${1#*=}"
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail_usage "unknown option: $1"
      ;;
  esac
done

case "$scope" in
  user|project) ;;
  *) fail_usage "unsupported scope: $scope" ;;
esac

command -v gh >/dev/null 2>&1 || {
  printf 'Result: failed\nFailed: gh command not found\n' >&2
  exit 1
}

if [ "$scope" = "user" ] && [ -z "${HOME:-}" ]; then
  printf 'Result: failed\nFailed: HOME is not set\n' >&2
  exit 1
fi

skills=()
for skill_dir in "$REPO_ROOT"/skills/*; do
  [ -d "$skill_dir" ] || continue
  [ -f "$skill_dir/SKILL.md" ] || continue
  skills+=("$(basename -- "$skill_dir")")
done

if [ "${#skills[@]}" -eq 0 ]; then
  printf 'Result: failed\nFailed: no skills found in %s/skills\n' "$REPO_ROOT" >&2
  exit 1
fi

project_root=""
if [ "$scope" = "project" ]; then
  if ! project_root="$(git -C "$INVOCATION_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    printf 'Result: failed\nFailed: project scope requires a Git repository\n' >&2
    exit 1
  fi
fi

target_dir_for() {
  case "$scope:$1" in
    user:codex)
      printf '%s/.codex/skills\n' "${HOME:?HOME is not set}"
      ;;
    user:claude-code)
      printf '%s/.claude/skills\n' "${HOME:?HOME is not set}"
      ;;
    project:codex)
      printf '%s/.agents/skills\n' "$project_root"
      ;;
    project:claude-code)
      printf '%s/.claude/skills\n' "$project_root"
      ;;
  esac
}

contains_skill() {
  local candidate="$1"
  local skill
  for skill in "${skills[@]}"; do
    [ "$skill" = "$candidate" ] && return 0
  done
  return 1
}

removed=()
collect_removed() {
  local agent="$1"
  local target_dir entry name
  target_dir="$(target_dir_for "$agent")"
  [ -d "$target_dir" ] || return

  for entry in "$target_dir"/*; do
    [ -d "$entry" ] || continue
    [ -f "$entry/SKILL.md" ] || continue
    name="$(basename -- "$entry")"
    if ! contains_skill "$name"; then
      removed+=("$agent/$name")
    fi
  done
}

for agent in "${agents[@]}"; do
  collect_removed "$agent"
done

print_items() {
  local label="$1"
  local item
  shift
  if [ "$#" -eq 0 ]; then
    printf '%s: none\n' "$label"
  else
    for item in "$@"; do
      printf '%s: %s\n' "$label" "$item"
    done
  fi
}

planned=()
for agent in "${agents[@]}"; do
  for skill in "${skills[@]}"; do
    planned+=("$agent/$skill")
  done
done

if [ "$dry_run" = true ]; then
  printf 'Result: dry-run\n'
  printf 'Scope: %s\n' "$scope"
  print_items "Install" "${planned[@]}"
  setup_planned=()
  if contains_skill agmsg; then
    for agent in "${agents[@]}"; do
      setup_planned+=("$agent/agmsg")
    done
  fi
  print_items "Setup" "${setup_planned[@]}"
  print_items "Uninstall" "${removed[@]}"
  exit 0
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/sync-skills.XXXXXX")" || {
  printf 'Result: failed\nFailed: could not create temporary directory\n' >&2
  exit 1
}

start_activity
if ! source_sha="$(gh api "repos/$SOURCE_REPO/commits/HEAD" --jq .sha 2>"$tmp_dir/api.err")"; then
  stop_activity failure
  printf 'Result: failed\nFailed: could not resolve %s default branch HEAD\n' "$SOURCE_REPO" >&2
  exit 1
fi
if [ "${#source_sha}" -ne 40 ]; then
  stop_activity failure
  printf 'Result: failed\nFailed: invalid commit SHA returned for %s\n' "$SOURCE_REPO" >&2
  exit 1
fi

installed=()
failed=()
for agent in "${agents[@]}"; do
  for skill in "${skills[@]}"; do
    if gh skill install "$SOURCE_REPO" "skills/$skill" \
      --agent "$agent" \
      --scope "$scope" \
      --pin "$source_sha" \
      --force \
      >"$tmp_dir/install.out" 2>"$tmp_dir/install.err"; then
      installed+=("$agent/$skill")
    else
      failed+=("$agent/$skill")
    fi
  done
done

if [ "${#failed[@]}" -gt 0 ]; then
  stop_activity failure
  printf 'Result: failed\n'
  printf 'Scope: %s\n' "$scope"
  print_items "Installed" "${installed[@]}"
  print_items "Failed" "${failed[@]}"
  printf 'Uninstalled: none\n'
  exit 1
fi

setup_failed=()
if contains_skill agmsg; then
  installer="$REPO_ROOT/skills/agmsg/agmsg.py"
  for agent in "${agents[@]}"; do
    target_dir="$(target_dir_for "$agent")"
    installed_skill="$target_dir/agmsg"
    # gh skill install --force may overlay files without removing paths that
    # disappeared upstream. Remove the retired shell implementation before
    # binding the installed Python skill to the shared runtime.
    rm -rf -- "$installed_skill/install.sh" "$installed_skill/scripts"
    if [ ! -f "$installer" ] || [ ! -f "$installed_skill/SKILL.md" ] || ! python3 "$installer" install \
      --repo-root "$REPO_ROOT" \
      --skill-dir "$installed_skill" \
      >"$tmp_dir/agmsg-setup-$agent.out" \
      2>"$tmp_dir/agmsg-setup-$agent.err"; then
      setup_failed+=("$agent/agmsg")
    fi
  done
fi

if [ "${#setup_failed[@]}" -gt 0 ]; then
  stop_activity failure
  printf 'Result: failed\n'
  printf 'Scope: %s\n' "$scope"
  print_items "Installed" "${installed[@]}"
  print_items "Setup failed" "${setup_failed[@]}"
  for item in "${setup_failed[@]}"; do
    agent="${item%%/*}"
    error_file="$tmp_dir/agmsg-setup-$agent.err"
    if [ -s "$error_file" ]; then
      printf 'Setup error (%s):\n' "$item"
      sed 's/^/  /' "$error_file"
    else
      printf 'Setup error (%s): source installer or installed skill missing\n' "$item"
    fi
  done
  printf 'Uninstalled: none\n'
  exit 1
fi

stop_activity success

for item in "${removed[@]}"; do
  agent="${item%%/*}"
  skill="${item#*/}"
  target_dir="$(target_dir_for "$agent")"
  rm -rf -- "$target_dir/$skill"
done

printf 'Result: synchronized\n'
printf 'Scope: %s\n' "$scope"
print_items "Installed" "${installed[@]}"
print_items "Uninstalled" "${removed[@]}"
