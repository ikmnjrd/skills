#!/usr/bin/env bash
set -euo pipefail

found_skill=false

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to validate vendor lock files" >&2
  exit 1
fi

for lock in vendor/*.lock.json; do
  [ -f "$lock" ] || continue
  if ! jq -e . "$lock" >/dev/null; then
    echo "Invalid vendor lock file: $lock" >&2
    exit 1
  fi
done

for skill in skills/*; do
  [ -d "$skill" ] || continue
  found_skill=true

  if [ ! -f "$skill/SKILL.md" ]; then
    echo "Missing SKILL.md: $skill" >&2
    exit 1
  fi

  is_vendored=false
  for lock in vendor/*.lock.json; do
    [ -f "$lock" ] || continue
    if jq -e --arg path "$skill" 'any(.[]; .localPath == $path)' "$lock" >/dev/null; then
      is_vendored=true
      break
    fi
  done

  if [ "$is_vendored" = true ] && [ ! -f "$skill/VENDOR.md" ]; then
    echo "Missing VENDOR.md for vendored skill: $skill" >&2
    exit 1
  fi

  if ! awk '
    NR == 1 {
      if ($0 != "---") {
        exit 1
      }
      in_frontmatter = 1
      next
    }

    in_frontmatter && $0 == "---" {
      closed = 1
      exit
    }

    in_frontmatter && /^name:[[:space:]]*[^[:space:]]/ {
      name = 1
    }

    in_frontmatter && /^description:[[:space:]]*[^[:space:]]/ {
      description = 1
    }

    END {
      if (!closed || !name || !description) {
        exit 1
      }
    }
  ' "$skill/SKILL.md"; then
    echo "Invalid frontmatter: $skill/SKILL.md" >&2
    exit 1
  fi
done

if [ "$found_skill" = false ]; then
  echo "No skills found" >&2
  exit 1
fi

echo "ok"
