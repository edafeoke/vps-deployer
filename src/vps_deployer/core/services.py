from __future__ import annotations

from pathlib import Path

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.projects import get_project
from vps_deployer.core.runtime import (
    AppRuntimeError,
    get_runtime,
    load_start_command,
)
from vps_deployer.core.validation import validate_project_name
from vps_deployer.db.models import Project

PROCESSLESS_RUNTIMES = frozenset({"static", "vite"})


class ServiceError(RuntimeError):
    """Raised when an application service cannot be started or stopped."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _current_release(project: Project) -> Path:
    root = Path(project.deployment_path)
    current = root / "current"
    if not current.exists():
        raise ServiceError("No active release. Deploy the project first.")
    return current.resolve()


def service_payload(project: Project, settings: Settings | None = None) -> dict[str, object]:
    runtime = get_runtime(settings)
    running = False
    if project.runtime not in PROCESSLESS_RUNTIMES:
        try:
            running = runtime.is_running(project)
        except AppRuntimeError:
            running = False
    return {
        "name": project.name,
        "service_name": project.service_name,
        "runtime": runtime.name,
        "app_runtime": project.runtime,
        "port": project.port,
        "running": running,
        "enabled": project.enabled,
    }


def start_project(name: str, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    project = get_project(validate_project_name(name), current)
    if not project.enabled:
        raise ServiceError("Project is disabled")
    if project.runtime in PROCESSLESS_RUNTIMES:
        return {
            **service_payload(project, current),
            "detail": "This runtime has no process",
        }
    runtime = get_runtime(current)
    if runtime.is_running(project):
        return {**service_payload(project, current), "detail": "Already running"}
    release = _current_release(project)
    command = load_start_command(Path(project.deployment_path))
    if command is None:
        raise ServiceError("No start command is stored for this project")
    try:
        runtime.start(project, release, command)
        runtime.wait_for_port(project)
    except AppRuntimeError as exc:
        raise ServiceError(str(exc), status_code=500) from exc
    return {**service_payload(project, current), "detail": "Started"}


def stop_project(name: str, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    project = get_project(validate_project_name(name), current)
    if project.runtime in PROCESSLESS_RUNTIMES:
        return {
            **service_payload(project, current),
            "detail": "This runtime has no process",
        }
    runtime = get_runtime(current)
    try:
        runtime.stop(project)
    except AppRuntimeError as exc:
        raise ServiceError(str(exc), status_code=500) from exc
    return {**service_payload(project, current), "detail": "Stopped"}


def restart_project(name: str, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    project = get_project(validate_project_name(name), current)
    if project.runtime in PROCESSLESS_RUNTIMES:
        return {
            **service_payload(project, current),
            "detail": "This runtime has no process",
        }
    stop_project(name, current)
    return start_project(name, current)


def project_service_status(name: str, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    project = get_project(validate_project_name(name), current)
    return service_payload(project, current)


def project_service_logs(
    name: str,
    lines: int = 200,
    settings: Settings | None = None,
) -> list[str]:
    current = settings or get_settings()
    project = get_project(validate_project_name(name), current)
    if project.runtime in PROCESSLESS_RUNTIMES:
        return []
    runtime = get_runtime(current)
    try:
        return runtime.service_logs(project, lines)
    except AppRuntimeError as exc:
        raise ServiceError(str(exc), status_code=500) from exc
