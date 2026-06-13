#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/test-remove-skill.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/scripts" "$tmp_dir/skills/original" \
  "$tmp_dir/skills/survivor" "$tmp_dir/skills/vendor-a" \
  "$tmp_dir/skills/vendor-b" \
  "$tmp_dir/vendor"
cp "$REPO_ROOT/scripts/remove-skill.sh" "$tmp_dir/scripts/"
cp "$REPO_ROOT/scripts/validate-skills.sh" "$tmp_dir/scripts/"

cat >"$tmp_dir/README.md" <<'EOF'
# Fixture

## 収録スキル

- `original` — Original.
- `survivor` — Survivor.
- `vendor-a` — Vendor A.
- `vendor-b` — Vendor B.

## Next
EOF

for skill in original survivor vendor-a vendor-b; do
  cat >"$tmp_dir/skills/$skill/SKILL.md" <<EOF
---
name: $skill
description: Test skill.
---
EOF
done

touch "$tmp_dir/skills/vendor-a/VENDOR.md"
touch "$tmp_dir/skills/vendor-b/VENDOR.md"
cat >"$tmp_dir/vendor/example.lock.json" <<'EOF'
{
  "vendor-a": {
    "upstream": "https://example.com/upstream",
    "localPath": "skills/vendor-a"
  },
  "vendor-b": {
    "upstream": "https://example.com/upstream",
    "localPath": "skills/vendor-b"
  }
}
EOF

before="$(find "$tmp_dir" -type f -print0 | sort -z | xargs -0 sha256sum)"
dry_run_output="$("$tmp_dir/scripts/remove-skill.sh" --dry-run vendor-a)"
after="$(find "$tmp_dir" -type f -print0 | sort -z | xargs -0 sha256sum)"
[ "$before" = "$after" ]
grep -q '^Result: dry-run$' <<<"$dry_run_output"
grep -q '^Update: vendor/example.lock.json$' <<<"$dry_run_output"

first_output="$("$tmp_dir/scripts/remove-skill.sh" vendor-a)"
[ ! -e "$tmp_dir/skills/vendor-a" ]
! grep -q '`vendor-a`' "$tmp_dir/README.md"
jq -e 'has("vendor-a") | not' "$tmp_dir/vendor/example.lock.json" >/dev/null
! grep -q '^Review attribution:' <<<"$first_output"

second_output="$("$tmp_dir/scripts/remove-skill.sh" vendor-b)"
[ ! -e "$tmp_dir/skills/vendor-b" ]
jq -e 'length == 0' "$tmp_dir/vendor/example.lock.json" >/dev/null
grep -q \
  '^Review attribution: https://example.com/upstream has no remaining vendored skills$' \
  <<<"$second_output"

"$tmp_dir/scripts/remove-skill.sh" original >/dev/null
[ ! -e "$tmp_dir/skills/original" ]
grep -q '^- `survivor`' "$tmp_dir/README.md"

if "$tmp_dir/scripts/remove-skill.sh" survivor >/dev/null 2>&1; then
  printf 'expected removal of the last skill to fail\n' >&2
  exit 1
fi
[ -d "$tmp_dir/skills/survivor" ]

printf 'ok\n'
