#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

dry_run=false
skill_name=""
tmp_dir=""

usage() {
  cat <<'EOF'
Usage: scripts/remove-skill.sh [--dry-run] SKILL

Remove a skill from skills/, the README skill list, and vendor lock files.

Options:
  --dry-run   Show the planned changes without modifying files.
  -h, --help  Show this help.
EOF
}

fail_usage() {
  printf 'Error: %s\n\n' "$1" >&2
  usage >&2
  exit 2
}

cleanup() {
  if [ -n "$tmp_dir" ]; then
    rm -rf -- "$tmp_dir"
  fi
}

trap cleanup EXIT

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      fail_usage "unknown option: $1"
      ;;
    *)
      [ -z "$skill_name" ] || fail_usage "only one skill may be removed at a time"
      skill_name="$1"
      shift
      ;;
  esac
done

[ -n "$skill_name" ] || fail_usage "SKILL is required"
case "$skill_name" in
  *[!a-z0-9-]*|''|-*|*-|*--*)
    fail_usage "invalid skill name: $skill_name"
    ;;
esac

command -v jq >/dev/null 2>&1 || {
  printf 'Result: failed\nFailed: jq command not found\n' >&2
  exit 1
}

skill_dir="$REPO_ROOT/skills/$skill_name"
if [ ! -d "$skill_dir" ] || [ -L "$skill_dir" ]; then
  printf 'Result: failed\nFailed: skill directory not found: skills/%s\n' \
    "$skill_name" >&2
  exit 1
fi
if [ ! -f "$skill_dir/SKILL.md" ]; then
  printf 'Result: failed\nFailed: SKILL.md not found: skills/%s/SKILL.md\n' \
    "$skill_name" >&2
  exit 1
fi

skill_count=0
for candidate in "$REPO_ROOT"/skills/*; do
  [ -f "$candidate/SKILL.md" ] || continue
  skill_count=$((skill_count + 1))
done
if [ "$skill_count" -le 1 ]; then
  printf 'Result: failed\nFailed: cannot remove the repository'\''s last skill\n' >&2
  exit 1
fi

readme="$REPO_ROOT/README.md"
[ -f "$readme" ] || {
  printf 'Result: failed\nFailed: README.md not found\n' >&2
  exit 1
}

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/remove-skill.XXXXXX")"
updated_readme="$tmp_dir/README.md"

if ! awk -v skill="$skill_name" '
  $0 == "## 収録スキル" {
    in_skill_list = 1
    print
    next
  }

  in_skill_list && /^## / {
    in_skill_list = 0
  }

  in_skill_list && index($0, "- `" skill "`") == 1 {
    removed++
    next
  }

  {
    print
  }

  END {
    if (removed != 1) {
      exit 1
    }
  }
' "$readme" >"$updated_readme"; then
  printf 'Result: failed\nFailed: expected one README entry for %s\n' \
    "$skill_name" >&2
  exit 1
fi

declare -a lock_files=()
declare -a removed_upstreams=()

has_removed_upstream() {
  local candidate="$1"
  local upstream

  if [ "${#removed_upstreams[@]}" -eq 0 ]; then
    return 1
  fi

  for upstream in "${removed_upstreams[@]}"; do
    if [ "$upstream" = "$candidate" ]; then
      return 0
    fi
  done

  return 1
}

for lock_file in "$REPO_ROOT"/vendor/*.lock.json; do
  [ -f "$lock_file" ] || continue
  if ! jq -e . "$lock_file" >/dev/null; then
    printf 'Result: failed\nFailed: invalid vendor lock file: %s\n' \
      "${lock_file#"$REPO_ROOT"/}" >&2
    exit 1
  fi

  local_path="skills/$skill_name"
  if jq -e --arg path "$local_path" \
    'any(.[]; .localPath == $path)' "$lock_file" >/dev/null; then
    lock_files+=("$lock_file")
    lock_output="$tmp_dir/$(basename -- "$lock_file")"
    jq --arg path "$local_path" \
      'with_entries(select(.value.localPath != $path))' \
      "$lock_file" >"$lock_output"

    while IFS= read -r upstream; do
      [ -n "$upstream" ] || continue
      if ! has_removed_upstream "$upstream"; then
        removed_upstreams+=("$upstream")
      fi
    done < <(
      jq -r --arg path "$local_path" \
        '.[] | select(.localPath == $path) | .upstream // empty' \
        "$lock_file"
    )
  fi
done

declare -a unused_upstreams=()
if [ "${#removed_upstreams[@]}" -gt 0 ]; then
  for upstream in "${removed_upstreams[@]}"; do
    remains=false
    for lock_file in "$REPO_ROOT"/vendor/*.lock.json; do
      [ -f "$lock_file" ] || continue
      lock_input="$lock_file"
      if [ -f "$tmp_dir/$(basename -- "$lock_file")" ]; then
        lock_input="$tmp_dir/$(basename -- "$lock_file")"
      fi
      if jq -e --arg upstream "$upstream" \
        'any(.[]; .upstream == $upstream)' "$lock_input" >/dev/null; then
        remains=true
        break
      fi
    done
    if [ "$remains" = false ]; then
      unused_upstreams+=("$upstream")
    fi
  done
fi

if [ "$dry_run" = true ]; then
  printf 'Result: dry-run\n'
else
  printf 'Planned result: removed\n'
fi
printf 'Skill: %s\n' "$skill_name"
printf 'Remove: skills/%s\n' "$skill_name"
printf 'Update: README.md\n'
if [ "${#lock_files[@]}" -gt 0 ]; then
  for lock_file in "${lock_files[@]}"; do
    printf 'Update: %s\n' "${lock_file#"$REPO_ROOT"/}"
  done
fi
if [ "${#unused_upstreams[@]}" -gt 0 ]; then
  for upstream in "${unused_upstreams[@]}"; do
    printf 'Review attribution: %s has no remaining vendored skills\n' "$upstream"
  done
fi

if [ "$dry_run" = true ]; then
  exit 0
fi

if ! (
  cd "$REPO_ROOT"
  bash scripts/validate-skills.sh
); then
  printf 'Result: failed\nFailed: repository validation failed before removal\n' >&2
  exit 1
fi

mv -- "$updated_readme" "$readme"
if [ "${#lock_files[@]}" -gt 0 ]; then
  for lock_file in "${lock_files[@]}"; do
    mv -- "$tmp_dir/$(basename -- "$lock_file")" "$lock_file"
  done
fi
rm -rf -- "$skill_dir"

if ! (
  cd "$REPO_ROOT"
  bash scripts/validate-skills.sh
); then
  printf 'Result: failed\nFailed: repository validation failed after removal\n' >&2
  exit 1
fi

printf 'Result: removed\n'
