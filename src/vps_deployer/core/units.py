from __future__ import annotations

from pathlib import Path

from vps_deployer.core.validation import (
    APPS_ROOT,
    UNSAFE_CHARS,
    validate_port,
    validate_project_name,
)

APP_SERVICE_PREFIX = "vps-deployer-app-"


class UnitError(ValueError):
    """Raised when a systemd unit cannot be rendered safely."""


def app_service_name(project_name: str) -> str:
    name = validate_project_name(project_name)
    return f"{APP_SERVICE_PREFIX}{name}"


def app_unit_name(project_name: str) -> str:
    return f"{app_service_name(project_name)}.service"


def validate_unit_workdir(path: Path, project_name: str) -> Path:
    name = validate_project_name(project_name)
    raw = Path(path)
    if not raw.is_absolute():
        raise UnitError("Working directory must be an absolute path")
    if ".." in raw.parts:
        raise UnitError("Working directory must not contain path traversal")
    root = APPS_ROOT / name
    try:
        raw.relative_to(root)
    except ValueError as exc:
        raise UnitError(f"Working directory must be under {root}/") from exc
    return raw


def _validate_exec_args(command: list[str]) -> list[str]:
    if not command:
        raise UnitError("ExecStart command is empty")
    for part in command:
        if not part or any(ch in part for ch in UNSAFE_CHARS):
            raise UnitError("ExecStart contains unsafe characters")
        if ".." in part:
            raise UnitError("ExecStart contains path traversal")
        if part in {"sh", "bash", "/bin/sh", "/bin/bash", "-c"}:
            raise UnitError("Shell ExecStart is not allowed")
    return command


def render_app_unit(
    *,
    project: str,
    port: int,
    workdir: Path,
    command: list[str],
) -> str:
    name = validate_project_name(project)
    port = validate_port(port)
    directory = validate_unit_workdir(workdir, name)
    args = _validate_exec_args(command)
    exec_start = " ".join(args)
    return (
        "[Unit]\n"
        f"Description=VPS Deployer application {name}\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=vps-deployer\n"
        "Group=vps-deployer\n"
        f"WorkingDirectory={directory}\n"
        "Environment=HOST=127.0.0.1\n"
        f"Environment=PORT={port}\n"
        "Environment=NODE_ENV=production\n"
        "Environment=PATH=/usr/local/bin:/usr/bin:/bin\n"
        f"EnvironmentFile=-/var/www/apps/{name}/shared/env\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
