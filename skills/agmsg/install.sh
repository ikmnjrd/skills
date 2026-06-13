#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT=""
SKILL_DIR="$SCRIPT_DIR"

usage() {
  cat <<'EOF'
Usage: install.sh [--repo-root PATH] [--skill-dir PATH]

Initialize agmsg runtime state and bind this installed skill copy to it.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo-root)
      [ "$#" -ge 2 ] || { echo "--repo-root requires a path" >&2; exit 2; }
      REPO_ROOT="$2"
      shift 2
      ;;
    --skill-dir)
      [ "$#" -ge 2 ] || { echo "--skill-dir requires a path" >&2; exit 2; }
      SKILL_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

is_skills_repo() {
  [ -f "$1/skills/agmsg/SKILL.md" ]
}

if [ -z "$REPO_ROOT" ] && [ -n "${AGMSG_REPO_ROOT:-}" ]; then
  REPO_ROOT="$AGMSG_REPO_ROOT"
fi

if [ -z "$REPO_ROOT" ] && [ -n "${HOME:-}" ] && is_skills_repo "$HOME/workspace/skills"; then
  REPO_ROOT="$HOME/workspace/skills"
fi

if [ -z "$REPO_ROOT" ]; then
  candidate="$SCRIPT_DIR"
  while [ "$candidate" != "/" ]; do
    if is_skills_repo "$candidate"; then
      REPO_ROOT="$candidate"
      break
    fi
    candidate="$(dirname "$candidate")"
  done
fi

if [ -z "$REPO_ROOT" ]; then
  echo "Could not locate the skills repository." >&2
  echo "Set AGMSG_REPO_ROOT or run install.sh --repo-root <path>." >&2
  exit 1
fi

REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
SKILL_DIR="$(cd "$SKILL_DIR" && pwd)"
if ! is_skills_repo "$REPO_ROOT"; then
  echo "Not a skills repository containing skills/agmsg: $REPO_ROOT" >&2
  exit 1
fi
if [ ! -f "$SKILL_DIR/SKILL.md" ] || [ ! -d "$SKILL_DIR/scripts" ]; then
  echo "Not an agmsg skill directory: $SKILL_DIR" >&2
  exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required but was not found." >&2
  exit 1
fi

RUNTIME_DIR="$REPO_ROOT/.agmsg"
mkdir -p "$RUNTIME_DIR/db" "$RUNTIME_DIR/teams" "$RUNTIME_DIR/run"
printf '%s\n' "$RUNTIME_DIR" > "$SKILL_DIR/runtime-path"

AGMSG_RUNTIME_DIR="$RUNTIME_DIR" bash "$SKILL_DIR/scripts/init-db.sh" >/dev/null
if [ ! -f "$RUNTIME_DIR/config.yaml" ]; then
  AGMSG_RUNTIME_DIR="$RUNTIME_DIR" bash "$SKILL_DIR/scripts/config.sh" show >/dev/null
fi

configure_codex() {
  [ -n "${HOME:-}" ] || return
  local config_dir config backup entry
  config_dir="$HOME/.codex"
  config="$config_dir/config.toml"
  mkdir -p "$config_dir"
  touch "$config"

  if grep -Fq "$RUNTIME_DIR" "$config"; then
    return
  fi

  backup="$config.bak"
  cp "$config" "$backup"
  entry="$RUNTIME_DIR"
  entry="${entry//\\/\\\\}"
  entry="${entry//\"/\\\"}"
  entry="\"$entry\""

  if grep -q '^[[:space:]]*writable_roots[[:space:]]*=' "$config"; then
    awk -v entry="$entry" '
      /^[[:space:]]*writable_roots[[:space:]]*=/ {
        in_roots=1
        tail=$0
        sub(/^.*\[/, "", tail)
        sub(/\].*$/, "", tail)
        if (tail ~ /"/) has_value=1
      }
      in_roots && !/^[[:space:]]*writable_roots[[:space:]]*=/ && /"/ {
        has_value=1
      }
      in_roots && /\]/ {
        if (has_value) {
          sub(/\]/, ", " entry "]")
        } else {
          sub(/\]/, entry "]")
        }
        in_roots=0
      }
      { print }
    ' "$config" > "$config.tmp"
    mv "$config.tmp" "$config"
  elif grep -q '^\[sandbox_workspace_write\]' "$config"; then
    awk -v entry="$entry" '
      { print }
      /^\[sandbox_workspace_write\]/ { print "writable_roots = [" entry "]" }
    ' "$config" > "$config.tmp"
    mv "$config.tmp" "$config"
  else
    printf '\n[sandbox_workspace_write]\nwritable_roots = [%s]\n' "$entry" >> "$config"
  fi
}

configure_codex

echo "agmsg initialized"
echo "runtime: $RUNTIME_DIR"
echo "skill: $SKILL_DIR"
