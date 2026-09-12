from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vps_deployer.cli.client import ApiRequestError
from vps_deployer.cli.main import app
from vps_deployer.core.version import get_version

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert get_version() in result.stdout


def test_doctor(tmp_env) -> None:
    result = runner.invoke(app, ["doctor"])
    assert "VPS Deployer doctor" in result.stdout
    assert "Operating system" in result.stdout
    assert "Database" in result.stdout


def test_status_requires_api(tmp_env) -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "not reachable" in result.stdout or "not reachable" in result.stderr


def test_projects_requires_api(tmp_env) -> None:
    result = runner.invoke(app, ["projects"])
    assert result.exit_code == 1


def _proxy_api(client: TestClient):
    def fake_request(method: str, path: str, json=None, settings=None, timeout: float = 2.0):
        response = client.request(method, path, json=json)
        if response.status_code >= 400:
            payload = response.json()
            detail = payload.get("detail", "Request failed")
            raise ApiRequestError(str(detail), response.status_code)
        if not response.content:
            return {}
        return response.json()

    return fake_request


def test_projects_list_via_api(tmp_env, client: TestClient, monkeypatch) -> None:
    fake = _proxy_api(client)
    monkeypatch.setattr("vps_deployer.cli.main.api_get", lambda path, **kw: fake("GET", path))
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "No projects yet." in result.stdout


def test_project_add_show_remove(tmp_env, client: TestClient, monkeypatch) -> None:
    fake = _proxy_api(client)
    monkeypatch.setattr("vps_deployer.cli.main.api_request", fake)
    monkeypatch.setattr("vps_deployer.cli.main.api_get", lambda path, **kw: fake("GET", path))

    added = runner.invoke(
        app,
        ["project", "add", "my-next-app", "--repository", "example/my-next-app"],
    )
    assert added.exit_code == 0, added.output
    assert "Created project my-next-app" in added.stdout

    shown = runner.invoke(app, ["project", "show", "my-next-app"])
    assert shown.exit_code == 0
    assert "repository: example/my-next-app" in shown.stdout

    listed = runner.invoke(app, ["project", "list"])
    assert listed.exit_code == 0
    assert "my-next-app" in listed.stdout

    removed = runner.invoke(app, ["project", "remove", "my-next-app", "--yes"])
    assert removed.exit_code == 0
    assert "Removed project my-next-app" in removed.stdout

    missing = runner.invoke(app, ["project", "show", "my-next-app"])
    assert missing.exit_code == 1


def test_project_add_rejects_invalid_name(tmp_env, client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("vps_deployer.cli.main.api_request", _proxy_api(client))
    result = runner.invoke(
        app,
        ["project", "add", "Bad Name", "--repository", "example/my-next-app"],
    )
    assert result.exit_code == 1


def test_github_configure_and_status(tmp_env) -> None:
    from conftest import make_github_pem

    key_file = tmp_env / "app.pem"
    key_file.write_text(make_github_pem(), encoding="utf-8")
    unconfigured = runner.invoke(app, ["github", "status"])
    assert unconfigured.exit_code == 1
    configured = runner.invoke(
        app,
        [
            "github",
            "configure",
            "--app-id",
            "12345",
            "--key-file",
            str(key_file),
            "--webhook-secret",
            "supersecret",
        ],
    )
    assert configured.exit_code == 0, configured.output
    status = runner.invoke(app, ["github", "status"])
    assert status.exit_code == 0
    assert "app_id: 12345" in status.stdout
    assert "supersecret" not in status.stdout
