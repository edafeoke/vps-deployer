from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Protocol

import httpx

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.helper import HelperError, helper_available, require_helper
from vps_deployer.core.units import render_app_unit, validate_unit_workdir
from vps_deployer.core.validation import APPS_ROOT, validate_project_name
from vps_deployer.db.models import Project

START_COMMAND_FILE = "start.json"


class AppRuntimeError(RuntimeError):
    """Raised when an application process fails to start or stay healthy."""


class RuntimeProvider(Protocol):
    name: str

    def start(self, project: Project, release_path: Path, command: list[str]) -> None: ...

    def stop(self, project: Project) -> None: ...

    def is_running(self, project: Project) -> bool: ...

    def wait_for_port(self, project: Project, timeout: float = 30.0) -> None: ...

    def http_health(self, project: Project, path: str = "/") -> None: ...

    def install(self, project: Project, release_path: Path, command: list[str]) -> None: ...

    def remove(self, project: Project) -> None: ...

    def service_logs(self, project: Project, lines: int = 200) -> list[str]: ...


def pid_file(project_root: Path) -> Path:
    return project_root / "shared" / "vps-deployer.pid"


def start_command_path(project_root: Path) -> Path:
    return project_root / "shared" / START_COMMAND_FILE


def persist_start_command(project_root: Path, command: list[str]) -> None:
    shared = project_root / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    start_command_path(project_root).write_text(
        json.dumps({"command": command}, indent=2) + "\n",
        encoding="utf-8",
    )


def load_start_command(project_root: Path) -> list[str] | None:
    path = start_command_path(project_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    command = payload.get("command") if isinstance(payload, dict) else None
    if isinstance(command, list) and all(isinstance(item, str) for item in command) and command:
        return command
    return None


def wait_for_port(project: Project, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", project.port)) == 0:
                return
        time.sleep(0.2)
    raise AppRuntimeError(f"Port 127.0.0.1:{project.port} did not start listening")


def http_health(project: Project, path: str = "/") -> None:
    url = f"http://127.0.0.1:{project.port}{path}"
    try:
        response = httpx.get(url, timeout=2.0)
    except httpx.HTTPError as exc:
        raise AppRuntimeError(f"Health check failed for {url}") from exc
    if response.status_code >= 500:
        raise AppRuntimeError(f"Health check HTTP {response.status_code} for {url}")


def read_app_log(project: Project, lines: int = 200) -> list[str]:
    path = Path(project.deployment_path) / "logs" / "app.log"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return text[-lines:]


def systemd_available() -> bool:
    return Path("/run/systemd/system").exists()


class ProcessRuntimeProvider:
    """Start application processes on 127.0.0.1. Used for local development."""

    name = "process"

    def start(self, project: Project, release_path: Path, command: list[str]) -> None:
        root = Path(project.deployment_path)
        persist_start_command(root, command)
        shared = root / "shared"
        shared.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HOST"] = "127.0.0.1"
        env["PORT"] = str(project.port)
        env["NODE_ENV"] = env.get("NODE_ENV", "production")
        log_path = root / "logs" / "app.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=release_path,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        pid_file(root).write_text(str(process.pid), encoding="utf-8")

    def stop(self, project: Project) -> None:
        root = Path(project.deployment_path)
        path = pid_file(root)
        if not path.is_file():
            return
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            path.unlink(missing_ok=True)
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            path.unlink(missing_ok=True)
            return
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        path.unlink(missing_ok=True)

    def is_running(self, project: Project) -> bool:
        root = Path(project.deployment_path)
        path = pid_file(root)
        if not path.is_file():
            return False
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            return True
        except (ValueError, OSError):
            return False

    def wait_for_port(self, project: Project, timeout: float = 30.0) -> None:
        wait_for_port(project, timeout)

    def http_health(self, project: Project, path: str = "/") -> None:
        http_health(project, path)

    def install(self, project: Project, release_path: Path, command: list[str]) -> None:
        persist_start_command(Path(project.deployment_path), command)

    def remove(self, project: Project) -> None:
        self.stop(project)

    def service_logs(self, project: Project, lines: int = 200) -> list[str]:
        return read_app_log(project, lines)


class SystemdRuntimeProvider:
    """Manage application systemd units through the privileged helper."""

    name = "systemd"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def _settings(self) -> Settings:
        return self.settings or get_settings()

    def start(self, project: Project, release_path: Path, command: list[str]) -> None:
        persist_start_command(Path(project.deployment_path), command)
        self.install(project, release_path, command)
        try:
            require_helper(
                "app-start",
                validate_project_name(project.name),
                settings=self._settings(),
            )
        except HelperError as exc:
            raise AppRuntimeError(str(exc)) from exc

    def stop(self, project: Project) -> None:
        try:
            require_helper(
                "app-stop",
                validate_project_name(project.name),
                settings=self._settings(),
            )
        except HelperError as exc:
            raise AppRuntimeError(str(exc)) from exc

    def is_running(self, project: Project) -> bool:
        try:
            result = require_helper(
                "app-status",
                validate_project_name(project.name),
                settings=self._settings(),
            )
        except HelperError:
            return False
        return (result.stdout or "").strip() == "active"

    def wait_for_port(self, project: Project, timeout: float = 30.0) -> None:
        wait_for_port(project, timeout)

    def http_health(self, project: Project, path: str = "/") -> None:
        http_health(project, path)

    def install(self, project: Project, release_path: Path, command: list[str]) -> None:
        persist_start_command(Path(project.deployment_path), command)
        try:
            workdir = validate_unit_workdir(Path(release_path), project.name)
        except Exception as exc:
            if not str(release_path).startswith(str(APPS_ROOT)):
                raise AppRuntimeError(
                    "systemd runtime requires application files under /var/www/apps/"
                ) from exc
            raise AppRuntimeError(str(exc)) from exc
        unit = render_app_unit(
            project=project.name,
            port=project.port,
            workdir=workdir,
            command=command,
        )
        try:
            require_helper(
                "app-unit-install",
                validate_project_name(project.name),
                settings=self._settings(),
                stdin=unit,
            )
        except HelperError as exc:
            raise AppRuntimeError(str(exc)) from exc

    def remove(self, project: Project) -> None:
        try:
            require_helper(
                "app-unit-remove",
                validate_project_name(project.name),
                settings=self._settings(),
            )
        except HelperError as exc:
            raise AppRuntimeError(str(exc)) from exc

    def service_logs(self, project: Project, lines: int = 200) -> list[str]:
        try:
            result = require_helper(
                "app-logs",
                validate_project_name(project.name),
                settings=self._settings(),
            )
        except HelperError as exc:
            raise AppRuntimeError(str(exc)) from exc
        output = result.stdout or ""
        return list(output.splitlines()[-lines:])


def get_runtime(settings: Settings | None = None) -> RuntimeProvider:
    current = settings or get_settings()
    choice = current.runtime
    if choice == "systemd":
        return SystemdRuntimeProvider(current)
    if choice == "process":
        return ProcessRuntimeProvider()
    if systemd_available() and helper_available(current):
        return SystemdRuntimeProvider(current)
    return ProcessRuntimeProvider()
