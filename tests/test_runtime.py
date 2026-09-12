from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vps_deployer.core.projects import ProjectCreate, allocate_port, create_project
from vps_deployer.core.runtime import (
    AppRuntimeError,
    ProcessRuntimeProvider,
    SystemdRuntimeProvider,
    get_runtime,
    load_start_command,
)
from vps_deployer.core.services import ServiceError, start_project, stop_project
from vps_deployer.core.units import UnitError, app_service_name, render_app_unit
from vps_deployer.core.validation import ValidationError
from vps_deployer.db.models import Project

SERVE_SCRIPT = """
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        return

HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
"""


def test_app_service_name() -> None:
    assert app_service_name("my-next-app") == "vps-deployer-app-my-next-app"
    with pytest.raises(ValidationError):
        app_service_name("../etc")


def test_render_app_unit_rejects_unsafe_command() -> None:
    with pytest.raises(UnitError):
        render_app_unit(
            project="my-next-app",
            port=33101,
            workdir=Path("/var/www/apps/my-next-app/current"),
            command=["bash", "-c", "reboot"],
        )
    with pytest.raises(UnitError):
        render_app_unit(
            project="my-next-app",
            port=33101,
            workdir=Path("/etc/passwd"),
            command=["npm", "start"],
        )


def test_get_runtime_honors_process_setting(tmp_env: Path) -> None:
    runtime = get_runtime()
    assert runtime.name == "process"


def test_process_start_stop_and_logs(tmp_env: Path) -> None:
    project = create_project(
        ProjectCreate(
            name="my-api",
            repository="example/my-api",
            runtime="node",
            port=allocate_port(),
        )
    )
    root = Path(project.deployment_path)
    release = root / "releases" / "r1"
    release.mkdir(parents=True)
    (root / "current").symlink_to(release)
    (release / "serve.py").write_text(SERVE_SCRIPT, encoding="utf-8")
    runtime = ProcessRuntimeProvider()
    runtime.start(project, release, ["python3", str(release / "serve.py")])
    try:
        runtime.wait_for_port(project, timeout=5)
        runtime.http_health(project)
        assert runtime.is_running(project)
        assert load_start_command(root) == ["python3", str(release / "serve.py")]
        logs = runtime.service_logs(project)
        assert isinstance(logs, list)
    finally:
        runtime.stop(project)
    assert not runtime.is_running(project)


def test_start_without_release(tmp_env: Path) -> None:
    create_project(
        ProjectCreate(name="my-api", repository="example/my-api", runtime="node", port=33121)
    )
    with pytest.raises(ServiceError):
        start_project("my-api")


def test_static_start_is_noop(tmp_env: Path) -> None:
    create_project(
        ProjectCreate(name="my-site", repository="example/my-site", runtime="static", port=33122)
    )
    payload = start_project("my-site")
    assert payload["running"] is False
    assert "no process" in str(payload["detail"])
    stopped = stop_project("my-site")
    assert stopped["running"] is False


def test_systemd_install_rejects_local_apps_root(tmp_env: Path, monkeypatch) -> None:
    project = create_project(
        ProjectCreate(name="my-api", repository="example/my-api", runtime="node", port=33123)
    )
    release = Path(project.deployment_path) / "releases" / "r1"
    release.mkdir(parents=True)
    provider = SystemdRuntimeProvider()

    def fail_helper(*args, **kwargs):
        raise AssertionError("helper should not be called for a local apps path")

    monkeypatch.setattr("vps_deployer.core.runtime.require_helper", fail_helper)
    with pytest.raises(AppRuntimeError):
        provider.install(project, release, ["npm", "start"])


def test_systemd_install_sends_unit_to_helper(monkeypatch) -> None:
    project = Project(
        name="my-api",
        repository="example/my-api",
        branch="main",
        runtime="node",
        deployment_path="/var/www/apps/my-api",
        port=33101,
        service_name="vps-deployer-app-my-api",
    )
    captured: dict[str, object] = {}

    def fake_helper(*args: str, settings=None, stdin: str | None = None):
        captured["args"] = args
        captured["stdin"] = stdin
        return subprocess.CompletedProcess(list(args), 0, "ok", "")

    monkeypatch.setattr("vps_deployer.core.runtime.require_helper", fake_helper)
    monkeypatch.setattr(
        "vps_deployer.core.runtime.persist_start_command", lambda *_args, **_kwargs: None
    )
    SystemdRuntimeProvider().install(
        project, Path("/var/www/apps/my-api/current"), ["npm", "start"]
    )
    assert captured["args"] == ("app-unit-install", "my-api")
    text = str(captured["stdin"])
    assert "User=vps-deployer" in text
    assert "WorkingDirectory=/var/www/apps/my-api/current" in text
    assert "Environment=PORT=33101" in text
    assert "ExecStart=npm start" in text


def test_api_service_routes(client: TestClient) -> None:
    created = client.post(
        "/api/projects",
        json={"name": "my-api", "repository": "example/my-api", "runtime": "node", "port": 33124},
    )
    assert created.status_code == 201
    assert created.json()["service_name"] == "vps-deployer-app-my-api"
    status = client.get("/api/projects/my-api/service")
    assert status.status_code == 200
    assert status.json()["running"] is False
    started = client.post("/api/projects/my-api/start")
    assert started.status_code == 409
    static = client.post(
        "/api/projects",
        json={
            "name": "my-site",
            "repository": "example/my-site",
            "runtime": "static",
            "port": 33125,
        },
    )
    assert static.status_code == 201
    noop = client.post("/api/projects/my-site/start")
    assert noop.status_code == 200
    assert noop.json()["running"] is False
    logs = client.get("/api/projects/my-site/service/logs")
    assert logs.status_code == 200
    assert logs.json()["lines"] == []
