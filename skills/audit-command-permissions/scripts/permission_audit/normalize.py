from __future__ import annotations

import re
import shlex
from pathlib import Path

from .redact import is_relative_to, redact_path, redact_text, redact_url

COMPOUND_RE = re.compile(r"(?:&&|\|\||[|;<>])")
DYNAMIC_RE = re.compile(r"(?:\$\(|`|\$\{|\$[A-Za-z_])")
URL_RE = re.compile(r"https?://[^\s\"']+")
NUMBER_RE = re.compile(r"^\d+$")

WRITE_COMMANDS = {
    "rm",
    "mv",
    "cp",
    "mkdir",
    "touch",
    "chmod",
    "chown",
    "install",
    "tee",
    "sed",
    "truncate",
    "dd",
}
INTERPRETERS = {"sh", "bash", "zsh", "fish", "python", "python3", "node", "ruby", "perl"}
SHELL_TOOLS = {"exec_command", "functions.exec_command", "Bash", "bash"}


def normalize_shell(command: str, cwd: Path, home: Path) -> dict:
    redacted = redact_text(command, home, cwd)
    features: set[str] = set()
    limitations: list[str] = []

    if COMPOUND_RE.search(command):
        features.add("shell_compound")
    if DYNAMIC_RE.search(command):
        features.add("dynamic_expansion")

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = []
        limitations.append("shell_parse_failed")

    if not tokens:
        return {
            "command": redacted,
            "executable": None,
            "normalized_shape": redacted,
            "parse_status": "ambiguous",
            "targets": extract_targets(command, [], cwd, home),
            "features": sorted(features),
            "limitations": limitations,
        }

    executable = Path(tokens[0]).name
    if executable in {"sudo", "doas", "pkexec"}:
        features.add("privilege_boundary")
    if executable in INTERPRETERS or executable in {"eval", "xargs"}:
        features.add("interpreter_execution")
    if executable in WRITE_COMMANDS:
        features.add("filesystem_write")
    if executable == "rm" and any(flag.startswith("-") and "r" in flag for flag in tokens[1:]):
        features.add("recursive_delete")
    if has_network_access(executable, tokens) or URL_RE.search(command):
        features.add("network_access")
    if is_network_write(executable, tokens):
        features.add("network_write")
    if executable == "wget" or (
        executable == "curl"
        and any(flag in tokens[1:] for flag in ("-o", "--output", "-O", "--remote-name"))
    ):
        features.add("filesystem_write")

    targets = extract_targets(command, tokens, cwd, home)
    for raw in raw_path_targets(tokens):
        expanded = expand_path(raw, cwd)
        if expanded and not is_relative_to(expanded, cwd):
            features.add("outside_project_path")

    shape_tokens = [shape_token(token, cwd, home) for token in tokens]
    parse_status = "ambiguous" if features.intersection({"shell_compound", "dynamic_expansion"}) else "parsed"
    if parse_status == "ambiguous":
        limitations.append("compound_or_dynamic_command_not_split")
        shape = redacted
    else:
        shape = shlex.join(shape_tokens)

    return {
        "command": redacted,
        "executable": executable,
        "normalized_shape": shape,
        "parse_status": parse_status,
        "targets": targets,
        "features": sorted(features),
        "limitations": limitations,
    }


def summarize_tool_input(tool: str, value: object, cwd: Path, home: Path) -> tuple[list[str], list[str]]:
    targets: list[str] = []
    features: set[str] = set()
    if isinstance(value, dict):
        for key in (
            "path",
            "file",
            "url",
            "uri",
            "target",
            "page_id",
            "database_id",
        ):
            item = value.get(key)
            if isinstance(item, str):
                targets.append(redact_target(item, cwd, home))
        patch = value.get("input")
        if isinstance(patch, str) and tool == "apply_patch":
            for match in re.finditer(
                r"^\*\*\* (?:Add|Update|Delete) File: (.+)$",
                patch,
                flags=re.MULTILINE,
            ):
                targets.append(redact_target(match.group(1), cwd, home))
        if tool in {"apply_patch", "write_file", "edit_file", "Write", "Edit", "MultiEdit"}:
            features.add("filesystem_write")
        if any(part in tool.lower() for part in ("web", "fetch", "search", "http", "mcp")):
            features.add("network_access")
    return sorted(set(targets)), sorted(features)


def extract_targets(command: str, tokens: list[str], cwd: Path, home: Path) -> list[str]:
    targets = [redact_url(url) for url in URL_RE.findall(command)]
    for token in raw_path_targets(tokens):
        targets.append(redact_path(str(expand_path(token, cwd) or token), home, cwd))
    return sorted(set(targets))


def raw_path_targets(tokens: list[str]) -> list[str]:
    result = []
    skip_next = False
    value_flags = {"-C", "--cwd", "-o", "--output", "-f", "--file", "--config"}
    for index, token in enumerate(tokens[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token in value_flags:
            if index + 1 < len(tokens):
                result.append(tokens[index + 1])
            skip_next = True
            continue
        if token.startswith("-") or "://" in token:
            continue
        if looks_like_path(token):
            result.append(token)
    return result


def looks_like_path(value: str) -> bool:
    return (
        value in {".", "..", "/", "~"}
        or value.startswith(("./", "../", "/", "~/"))
        or "/" in value
        or value.endswith((".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".log"))
    )


def expand_path(value: str, cwd: Path) -> Path | None:
    if "://" in value or value.startswith("<"):
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else cwd / path


def shape_token(token: str, cwd: Path, home: Path) -> str:
    if URL_RE.fullmatch(token):
        return "<URL>"
    if NUMBER_RE.fullmatch(token):
        return "<NUMBER>"
    if looks_like_path(token):
        expanded = expand_path(token, cwd)
        if expanded and is_relative_to(expanded, cwd):
            return "<PROJECT_PATH>"
        return "<OUTSIDE_PATH>"
    return redact_text(token, home, cwd)


def redact_target(value: str, cwd: Path, home: Path) -> str:
    if "://" in value:
        return redact_url(value)
    if looks_like_path(value):
        return redact_path(str(expand_path(value, cwd) or value), home, cwd)
    return redact_text(value, home, cwd)


def is_network_write(executable: str, tokens: list[str]) -> bool:
    args = set(tokens[1:])
    if executable == "curl" and (
        args.intersection({"-d", "--data", "--data-raw", "--data-binary", "-T", "--upload-file"})
        or args.intersection({"POST", "PUT", "PATCH", "DELETE"})
    ):
        return True
    if executable in {"scp", "rsync", "ssh"}:
        return True
    if executable == "git" and args.intersection({"push", "fetch", "pull", "clone"}):
        return "push" in args
    if executable == "gh" and args.intersection({"merge", "create", "delete", "close", "edit"}):
        return True
    if executable in {"npm", "pnpm", "yarn", "pip", "cargo"} and args.intersection(
        {"install", "add", "update", "publish"}
    ):
        return True
    if executable in {"kubectl", "docker"} and args.intersection(
        {"apply", "delete", "create", "run", "push", "exec"}
    ):
        return True
    return False


def has_network_access(executable: str, tokens: list[str]) -> bool:
    args = set(tokens[1:])
    if executable in {"curl", "wget", "ssh", "scp", "rsync", "gh", "kubectl"}:
        return True
    if executable == "git":
        return bool(args.intersection({"push", "fetch", "pull", "clone", "ls-remote"}))
    if executable in {"npm", "pnpm", "yarn", "pip", "cargo"}:
        return bool(args.intersection({"install", "add", "update", "publish", "search"}))
    if executable == "docker":
        return bool(args.intersection({"pull", "push", "login", "run", "exec"}))
    return False
