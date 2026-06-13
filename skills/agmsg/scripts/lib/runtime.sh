#!/usr/bin/env bash

agmsg_skill_dir() {
  local lib_dir
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$lib_dir/../.." && pwd
}

agmsg_runtime_dir() {
  if [ -n "${AGMSG_RUNTIME_DIR:-}" ]; then
    printf '%s\n' "${AGMSG_RUNTIME_DIR%/}"
    return
  fi

  local skill_dir runtime_file runtime_dir
  skill_dir="$(agmsg_skill_dir)"
  runtime_file="$skill_dir/runtime-path"

  if [ ! -f "$runtime_file" ]; then
    echo "agmsg is not initialized: missing $runtime_file" >&2
    echo "Run $skill_dir/install.sh first." >&2
    return 1
  fi

  IFS= read -r runtime_dir < "$runtime_file"
  if [ -z "$runtime_dir" ] || [ ! -d "$runtime_dir" ]; then
    echo "agmsg runtime is unavailable: $runtime_dir" >&2
    echo "Re-run $skill_dir/install.sh after moving the skills repository." >&2
    return 1
  fi

  printf '%s\n' "${runtime_dir%/}"
}

agmsg_teams_dir() {
  printf '%s/teams\n' "$(agmsg_runtime_dir)"
}

agmsg_run_dir() {
  printf '%s/run\n' "$(agmsg_runtime_dir)"
}

agmsg_config_path() {
  printf '%s/config.yaml\n' "$(agmsg_runtime_dir)"
}
