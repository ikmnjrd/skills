from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

SECRET_PATH_PARTS = {
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    ".config/gcloud",
    "credentials",
    "id_rsa",
    "id_ed25519",
    ".netrc",
}

TOKEN_PATTERNS = [
    re.compile(r"(?i)(authorization:\s*(?:bearer|basic)\s+)\S+"),
    re.compile(r"(?i)\b(token|api[_-]?key|password|passwd|secret)=([^\s&]+)"),
    re.compile(
        r"(?i)(\b[A-Za-z0-9_]*(?:token|api_?key|secret|password|passwd)"
        r"[A-Za-z0-9_]*=)([^\s&]+)"
    ),
    re.compile(r"(?i)(--?(?:token|api[_-]?key|secret|password|passwd)\s+)(\S+)"),
    re.compile(r"\b(?:ghp|github_pat|sk|xox[baprs])_[A-Za-z0-9_-]{8,}\b"),
]
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"https?://[^\s\"']+")


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def redact_text(value: str, home: Path, project: Path | None = None) -> str:
    result = URL_RE.sub(lambda match: redact_url(match.group(0)), value)
    for pattern in TOKEN_PATTERNS:
        if pattern.groups == 2:
            result = pattern.sub(lambda match: f"{match.group(1)}<TOKEN>", result)
        elif pattern.groups == 1:
            result = pattern.sub(lambda match: f"{match.group(1)}<TOKEN>", result)
        else:
            result = pattern.sub("<TOKEN>", result)
    result = EMAIL_RE.sub("<EMAIL>", result)

    if project:
        project_text = str(project)
        result = result.replace(project_text, "<PROJECT>")
    result = result.replace(str(home), "<HOME>")
    return redact_secret_paths(result)


def redact_path(path: str, home: Path, project: Path | None = None) -> str:
    expanded = Path(path).expanduser()
    text = str(expanded)
    if is_secret_path(text):
        return "<SECRET_PATH>"
    if text == "/":
        return "<FILESYSTEM_ROOT>"
    if expanded == home:
        return "<HOME_ROOT>"
    if project and is_relative_to(expanded, project):
        relative = expanded.resolve(strict=False).relative_to(project.resolve(strict=False))
        return "." if str(relative) == "." else str(relative)
    return redact_text(text, home, project=None)


def redact_secret_paths(value: str) -> str:
    for marker in sorted(SECRET_PATH_PARTS, key=len, reverse=True):
        escaped = re.escape(marker)
        value = re.sub(rf"(?:<HOME>|~|/[^\s\"']*)?/{escaped}(?:/[^\s\"']*)?", "<SECRET_PATH>", value)
    return value


def is_secret_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return any(
        f"/{part}" in normalized or normalized.endswith(part)
        for part in SECRET_PATH_PARTS
    )


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        host = parts.hostname or "<HOST>"
        port_number = parts.port
    except ValueError:
        return "<URL>"
    port = f":{port_number}" if port_number else ""
    path = parts.path or "/"
    return f"{parts.scheme}://{host}{port}{path}<URL_QUERY>"
