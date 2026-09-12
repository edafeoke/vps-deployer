from __future__ import annotations

import re
from pathlib import Path

PROJECT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._@:-]*$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
UNSAFE_CHARS = set(";&|`$(){}[]<>\\\"'\n\r\t*?")
APPS_ROOT = Path("/var/www/apps")
PORT_RANGE = range(33000, 34000)
ALLOWED_RUNTIMES = frozenset(
    {"nextjs", "node", "vite", "static", "fastapi", "flask", "laravel", "php"}
)


class ValidationError(ValueError):
    """Raised when user-supplied identity or path input is unsafe."""


def _reject_unsafe(value: str, label: str) -> str:
    if any(ch in UNSAFE_CHARS for ch in value):
        raise ValidationError(f"Invalid {label}: contains unsafe characters")
    if ".." in value:
        raise ValidationError(f"Invalid {label}: path traversal is not allowed")
    return value


def validate_project_name(name: str) -> str:
    if not name or not PROJECT_NAME_RE.fullmatch(name):
        raise ValidationError(
            "Invalid project name. Use a lowercase name starting with a letter, "
            "then letters, digits, or hyphens (2–63 characters)."
        )
    return _reject_unsafe(name, "project name")


def validate_service_name(name: str) -> str:
    if not name or not SERVICE_NAME_RE.fullmatch(name) or ".." in name:
        raise ValidationError("Invalid service name")
    return _reject_unsafe(name, "service name")


def validate_branch(branch: str) -> str:
    if not branch or branch.startswith("-") or branch.endswith(".lock"):
        raise ValidationError("Invalid git branch")
    if any(ch in branch for ch in ("..", "\\", " ", "~", "^", ":", "?", "*", "[")):
        raise ValidationError("Invalid git branch")
    return _reject_unsafe(branch, "branch")


def validate_repository(repository: str) -> str:
    if not repository or "/" not in repository or repository.startswith("/"):
        raise ValidationError("Invalid repository. Use owner/name.")
    _reject_unsafe(repository, "repository")
    owner, _, repo = repository.partition("/")
    if not owner or not repo or "/" in repo:
        raise ValidationError("Invalid repository. Use owner/name.")
    return repository


def validate_domain(domain: str) -> str:
    candidate = domain.strip().lower().rstrip(".")
    if candidate.startswith("*.") or not DOMAIN_RE.fullmatch(candidate):
        raise ValidationError("Invalid domain")
    return _reject_unsafe(candidate, "domain")


def validate_email(email: str) -> str:
    candidate = email.strip()
    if not candidate or not EMAIL_RE.fullmatch(candidate) or ".." in candidate:
        raise ValidationError("Invalid email address")
    return _reject_unsafe(candidate, "email")


def validate_port(port: int) -> int:
    if port not in PORT_RANGE:
        raise ValidationError(f"Port must be in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}")
    return port


def validate_runtime(runtime: str) -> str:
    candidate = runtime.strip().lower()
    if candidate not in ALLOWED_RUNTIMES:
        allowed = ", ".join(sorted(ALLOWED_RUNTIMES))
        raise ValidationError(f"Invalid runtime. Supported: {allowed}")
    return candidate


def validate_env_name(name: str) -> str:
    if not name or not ENV_NAME_RE.fullmatch(name):
        raise ValidationError("Invalid environment variable name")
    return name


def validate_app_path(
    path: str | Path,
    project_name: str | None = None,
    root: Path | None = None,
) -> Path:
    apps_root = root or APPS_ROOT
    raw = Path(path)
    message = f"Application path must be under {apps_root}/"
    if raw.is_absolute() and not str(raw).startswith(str(apps_root)):
        raise ValidationError(message)
    resolved = raw if not raw.exists() else raw.resolve()
    root_resolved = apps_root.resolve() if apps_root.exists() else apps_root
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        if raw.is_absolute():
            raise ValidationError(message) from exc
        resolved = (apps_root / raw).resolve() if apps_root.exists() else apps_root / raw
        try:
            resolved.relative_to(root_resolved if root_resolved.exists() else apps_root)
        except ValueError as inner:
            raise ValidationError(message) from inner
    if ".." in raw.parts:
        raise ValidationError(message)
    if project_name:
        validate_project_name(project_name)
        if resolved.name != project_name and raw.name != project_name:
            raise ValidationError("Application path must match the project name")
    return resolved
