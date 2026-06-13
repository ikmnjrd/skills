#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
FIXTURE_ROOT="$REPO_ROOT/tests/e2e/fixtures/skills"
TMP_ROOT="$REPO_ROOT/.test-tmp/skill-nesting"
ARTIFACT_ROOT="$REPO_ROOT/.test-artifacts/skill-nesting"

CHILD_SKILL="skill-e2e-nesting-child"
PARENT_SKILL="skill-e2e-nesting-parent"
TIMEOUT_SECONDS="${SKILL_E2E_TIMEOUT:-120}"

agents=("codex" "claude-code")
agent_option_seen=false
run_dir=""
artifact_dir=""
all_passed=true
case_failure_reason=""

usage() {
  cat <<'EOF'
Usage: scripts/test-skill.sh [options]

Run live E2E tests for explicit and nested skill invocation.

Options:
  --agent AGENT   Target agent: codex or claude-code. May be repeated.
  -h, --help      Show this help.

Environment:
  SKILL_E2E_TIMEOUT   Per-invocation timeout in seconds. Default: 120.
  CODEX_E2E_MODEL     Optional Codex model override.
  CLAUDE_E2E_MODEL    Optional Claude Code model override.
EOF
}

fail_usage() {
  printf 'Error: %s\n\n' "$1" >&2
  usage >&2
  exit 2
}

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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail_usage "unknown option: $1"
      ;;
  esac
done

case "$TIMEOUT_SECONDS" in
  ''|*[!0-9]*) fail_usage "SKILL_E2E_TIMEOUT must be a positive integer" ;;
  0) fail_usage "SKILL_E2E_TIMEOUT must be greater than zero" ;;
esac

for command_name in git jq timeout; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'Result: failed\nFailed: %s command not found\n' "$command_name" >&2
    exit 1
  }
done

for skill in "$CHILD_SKILL" "$PARENT_SKILL"; do
  [ -f "$FIXTURE_ROOT/$skill/SKILL.md" ] || {
    printf 'Result: failed\nFailed: fixture not found: %s\n' \
      "$FIXTURE_ROOT/$skill/SKILL.md" >&2
    exit 1
  }
done

cleanup() {
  if [ -n "$run_dir" ] && [ -d "$run_dir" ]; then
    rm -rf -- "$run_dir"
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
run_dir="$TMP_ROOT/$run_id"
artifact_dir="$ARTIFACT_ROOT/$run_id"
nonce="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"

mkdir -p "$run_dir/.agents/skills" "$run_dir/.claude/skills" "$artifact_dir"
cp -R "$FIXTURE_ROOT/." "$run_dir/.agents/skills/"
cp -R "$FIXTURE_ROOT/." "$run_dir/.claude/skills/"

for skill_root in "$run_dir/.agents/skills" "$run_dir/.claude/skills"; do
  sed -i "s/{{CHILD_NONCE}}/$nonce/g" \
    "$skill_root/$CHILD_SKILL/SKILL.md"
done

git -C "$run_dir" init -q

extract_codex_final() {
  local input="$1"
  local output="$2"

  jq -r '
    select(.type == "item.completed")
    | select(.item.type == "agent_message")
    | .item.text // empty
  ' "$input" >"$output" 2>/dev/null
}

extract_claude_final() {
  local input="$1"
  local output="$2"

  jq -r '
    select(.type == "result")
    | .result // empty
  ' "$input" >"$output" 2>/dev/null
}

validate_direct_output() {
  local final_output="$1"
  local expected="CHILD_RESULT:999 nonce=$nonce"
  local marker_output

  marker_output="$(
    sed -n '/^\(PARENT_\|CHILD_\)/p' "$final_output"
  )"
  [ "$marker_output" = "$expected" ]
}

validate_nested_output() {
  local final_output="$1"
  local expected_file="$artifact_dir/expected-nested.txt"
  local marker_file="$artifact_dir/actual-nested-markers.txt"

  cat >"$expected_file" <<EOF
PARENT_ATTEMPT:1
CHILD_RESULT:999 nonce=$nonce
PARENT_ATTEMPT:2
CHILD_RESULT:999 nonce=$nonce
PARENT_ATTEMPT:3
CHILD_RESULT:999 nonce=$nonce
PARENT_GAVE_UP expected=5 actual=999 attempts=3
EOF

  sed -n '/^\(PARENT_\|CHILD_\)/p' "$final_output" >"$marker_file"
  cmp -s "$expected_file" "$marker_file"
}

claude_invoked_child() {
  local raw_output="$1"

  jq -e --arg skill "$CHILD_SKILL" '
    .. | objects
    | select(.name? == "Skill")
    | select((.input? | tostring) | contains($skill))
  ' "$raw_output" >/dev/null 2>&1
}

run_codex() {
  local case_name="$1"
  local prompt="$2"
  local raw_output="$artifact_dir/codex-$case_name.jsonl"
  local stderr_output="$artifact_dir/codex-$case_name.stderr.log"
  local final_output="$artifact_dir/codex-$case_name.final.txt"
  local -a command=(
    codex exec
    --json
    --ephemeral
    --sandbox read-only
    --cd "$run_dir"
  )

  if [ -n "${CODEX_E2E_MODEL:-}" ]; then
    command+=(--model "$CODEX_E2E_MODEL")
  fi
  command+=("$prompt")

  case_failure_reason=""
  timeout "$TIMEOUT_SECONDS" "${command[@]}" \
    >"$raw_output" 2>"$stderr_output"
  local exit_code=$?
  if [ "$exit_code" -eq 124 ]; then
    case_failure_reason="timeout-${TIMEOUT_SECONDS}s"
    return 1
  fi
  if [ "$exit_code" -ne 0 ]; then
    case_failure_reason="cli-exit-$exit_code"
    return 1
  fi

  if ! extract_codex_final "$raw_output" "$final_output"; then
    case_failure_reason="invalid-structured-output"
    return 1
  fi

  CODEX_FINAL_OUTPUT="$final_output"
}

run_claude() {
  local case_name="$1"
  local prompt="$2"
  local raw_output="$artifact_dir/claude-code-$case_name.jsonl"
  local stderr_output="$artifact_dir/claude-code-$case_name.stderr.log"
  local final_output="$artifact_dir/claude-code-$case_name.final.txt"
  local -a command=(
    claude
    --print
    --verbose
    --output-format stream-json
    --permission-mode dontAsk
    --tools Skill
    --no-session-persistence
    --setting-sources project
  )

  if [ -n "${CLAUDE_E2E_MODEL:-}" ]; then
    command+=(--model "$CLAUDE_E2E_MODEL")
  fi
  command+=("$prompt")

  case_failure_reason=""
  (
    cd "$run_dir" &&
      timeout "$TIMEOUT_SECONDS" "${command[@]}" \
        >"$raw_output" 2>"$stderr_output"
  )
  local exit_code=$?
  if [ "$exit_code" -eq 124 ]; then
    case_failure_reason="timeout-${TIMEOUT_SECONDS}s"
    return 1
  fi
  if [ "$exit_code" -ne 0 ]; then
    case_failure_reason="cli-exit-$exit_code"
    return 1
  fi

  if ! extract_claude_final "$raw_output" "$final_output"; then
    case_failure_reason="invalid-structured-output"
    return 1
  fi

  CLAUDE_RAW_OUTPUT="$raw_output"
  CLAUDE_FINAL_OUTPUT="$final_output"
}

print_pass() {
  printf 'PASS: %s/%s\n' "$1" "$2"
}

print_fail() {
  local reason="${3:-failed}"
  printf 'FAIL: %s/%s reason=%s\n' "$1" "$2" "$reason"
  all_passed=false
}

print_skip() {
  printf 'SKIP: %s/%s prerequisite-failed\n' "$1" "$2"
}

pass_codex_direct_invocation() {
  # codex exec JSON does not expose a dedicated skill-injection event. The
  # per-run nonce exists only in the copied child SKILL.md, so reproducing it
  # is the observable proof that Codex loaded the skill body.
  validate_direct_output "$CODEX_FINAL_OUTPUT"
}

pass_codex_nested_invocation() {
  validate_nested_output "$CODEX_FINAL_OUTPUT"
}

pass_claude_direct_invocation() {
  validate_direct_output "$CLAUDE_FINAL_OUTPUT"
}

pass_claude_nested_invocation() {
  validate_nested_output "$CLAUDE_FINAL_OUTPUT" &&
    claude_invoked_child "$CLAUDE_RAW_OUTPUT"
}

run_codex_tests() {
  local agent="codex"

  if ! command -v codex >/dev/null 2>&1; then
    print_fail "$agent" "explicit-invocation" "command-not-found"
    print_skip "$agent" "nested-invocation"
    return
  fi

  # Codex explicitly invokes project skills with a $name mention.
  if ! run_codex "explicit-invocation" \
    "\$$CHILD_SKILL Return only the marker required by this skill."; then
    print_fail "$agent" "explicit-invocation" "$case_failure_reason"
    print_skip "$agent" "nested-invocation"
    return
  elif pass_codex_direct_invocation; then
    print_pass "$agent" "explicit-invocation"
  else
    print_fail "$agent" "explicit-invocation" "output-mismatch"
    print_skip "$agent" "nested-invocation"
    return
  fi

  if ! run_codex "nested-invocation" \
    "\$$PARENT_SKILL Run the nested skill invocation test exactly as instructed."; then
    print_fail "$agent" "nested-invocation" "$case_failure_reason"
  elif pass_codex_nested_invocation; then
    print_pass "$agent" "nested-invocation"
  else
    print_fail "$agent" "nested-invocation" "output-mismatch"
  fi
}

run_claude_tests() {
  local agent="claude-code"

  if ! command -v claude >/dev/null 2>&1; then
    print_fail "$agent" "explicit-invocation" "command-not-found"
    print_skip "$agent" "nested-invocation"
    return
  fi

  # Claude Code explicitly invokes project skills with a /name command.
  if ! run_claude "explicit-invocation" \
    "/$CHILD_SKILL"; then
    print_fail "$agent" "explicit-invocation" "$case_failure_reason"
    print_skip "$agent" "nested-invocation"
    return
  elif pass_claude_direct_invocation; then
    print_pass "$agent" "explicit-invocation"
  else
    print_fail "$agent" "explicit-invocation" "output-mismatch"
    print_skip "$agent" "nested-invocation"
    return
  fi

  if ! run_claude "nested-invocation" \
    "/$PARENT_SKILL"; then
    print_fail "$agent" "nested-invocation" "$case_failure_reason"
  elif pass_claude_nested_invocation; then
    print_pass "$agent" "nested-invocation"
  else
    print_fail "$agent" "nested-invocation" \
      "output-or-skill-tool-proof-mismatch"
  fi
}

for agent in "${agents[@]}"; do
  case "$agent" in
    codex) run_codex_tests ;;
    claude-code) run_claude_tests ;;
  esac
done

if [ "$all_passed" = true ]; then
  rm -rf -- "$artifact_dir"
  printf 'Result: passed\n'
  exit 0
fi

printf 'Artifacts: %s\n' "$artifact_dir"
printf 'Result: failed\n'
exit 1
