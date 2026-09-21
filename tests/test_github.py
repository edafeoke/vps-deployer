from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import jwt
from fastapi.testclient import TestClient

from conftest import make_github_pem
from vps_deployer.core.github import (
    begin_github_manifest,
    complete_github_manifest,
    configure_github,
    create_app_jwt,
    github_status,
)


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _configure(tmp_env: Path, secret: str = "supersecret") -> str:
    from vps_deployer.core.config import get_settings

    pem = make_github_pem()
    configure_github(
        app_id="12345",
        private_key=pem,
        webhook_secret=secret,
        installation_id="67890",
        settings=get_settings(),
    )
    return pem


def test_configure_writes_restricted_files(tmp_env: Path) -> None:
    _configure(tmp_env)
    key = tmp_env / "config" / "github-app.pem"
    secret = tmp_env / "config" / "github-webhook-secret"
    assert key.is_file()
    assert secret.is_file()
    assert (tmp_env / "config" / "github.json").is_file()
    assert "PRIVATE KEY" in key.read_text(encoding="utf-8")
    assert secret.read_text(encoding="utf-8").strip() == "supersecret"
    assert (key.stat().st_mode & 0o777) == 0o600
    assert (secret.stat().st_mode & 0o777) == 0o600
    status = github_status(probe=False)
    assert status["configured"] is True
    assert status["app_id"] == "12345"
    assert status["webhook_path"] == "/api/github/webhook"
    assert status["webhook_url"] is None
    assert "supersecret" not in json.dumps(status)


def test_root_configuration_assigns_files_to_service_user(tmp_env: Path, monkeypatch) -> None:
    from vps_deployer.core.config import get_settings

    settings = get_settings()
    assert settings.config_dir is not None
    monkeypatch.setattr("vps_deployer.core.github.PRODUCTION_CONFIG_DIR", settings.config_dir)
    monkeypatch.setattr(
        "vps_deployer.core.github.pwd.getpwnam",
        lambda _name: SimpleNamespace(pw_uid=123, pw_gid=456),
    )
    monkeypatch.setattr("vps_deployer.core.github.os.geteuid", lambda: 0)
    ownership: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(
        "vps_deployer.core.github.os.chown",
        lambda path, uid, gid: ownership.append((Path(path), uid, gid)),
    )

    _configure(tmp_env)

    assert {path.name for path, _, _ in ownership} == {
        "github-app.pem",
        "github-webhook-secret",
        "github.json",
    }
    assert all((uid, gid) == (123, 456) for _, uid, gid in ownership)


def test_github_status_reports_unreadable_metadata(tmp_env: Path, monkeypatch) -> None:
    _configure(tmp_env)
    original = Path.read_text

    def denied(path: Path, *args, **kwargs):
        if path.name == "github.json":
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    status = github_status(probe=False)
    assert status["configured"] is True
    assert status["authenticated"] is False
    assert "not readable" in str(status["error"])


def test_github_status_webhook_url_from_published_host(tmp_env: Path) -> None:
    from vps_deployer.core.config import get_settings
    from vps_deployer.core.dashboard_access import enable_dashboard_access

    _configure(tmp_env)
    enable_dashboard_access(
        hosts=["panel.example.com"],
        password="secretpass",
        settings=get_settings(),
    )
    status = github_status(probe=False)
    assert status["webhook_url"] == "http://panel.example.com/api/github/webhook"


def test_create_app_jwt(tmp_env: Path) -> None:
    _configure(tmp_env)
    token = create_app_jwt(now=1_700_000_000)
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["iss"] == "12345"


def test_github_manifest_creates_and_stores_app(tmp_env: Path, monkeypatch) -> None:
    from vps_deployer.core.config import get_settings
    from vps_deployer.core.dashboard_access import enable_dashboard_access

    enable_dashboard_access(
        hosts=["panel.example.com"],
        password="secretpass",
        settings=get_settings(),
    )
    handshake = begin_github_manifest()
    manifest = json.loads(handshake.manifest)
    assert manifest["hook_attributes"]["url"] == (
        "http://panel.example.com/api/github/webhook"
    )
    assert manifest["default_permissions"]["contents"] == "read"
    assert manifest["default_events"] == ["push"]

    class Response:
        status_code = 201

        @staticmethod
        def json():
            return {
                "id": 12345,
                "pem": make_github_pem(),
                "webhook_secret": "generated-by-github",
                "html_url": "https://github.com/apps/vps-deployer-test",
            }

    monkeypatch.setattr("vps_deployer.core.github.httpx.post", lambda *args, **kwargs: Response())
    install_url = complete_github_manifest("temporary-code", handshake.state)
    assert install_url == "https://github.com/apps/vps-deployer-test/installations/new"
    status = github_status(probe=False)
    assert status["configured"] is True
    assert status["app_id"] == "12345"
    assert not (tmp_env / "config" / "github-manifest-state.json").exists()


def test_webhook_rejects_missing_and_invalid_signature(client: TestClient, tmp_env: Path) -> None:
    body = b'{"zen":"ok"}'
    missing = client.post("/api/github/webhook", content=body)
    assert missing.status_code == 503

    _configure(tmp_env)
    missing = client.post(
        "/api/github/webhook",
        content=body,
        headers={"X-GitHub-Event": "ping"},
    )
    assert missing.status_code == 401

    invalid = client.post(
        "/api/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )
    assert invalid.status_code == 401


def test_webhook_ping_and_push_queue(client: TestClient, tmp_env: Path) -> None:
    secret = "supersecret"
    _configure(tmp_env, secret)
    created = client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "branch": "main"},
    )
    assert created.status_code == 201

    ping_body = b'{"zen":"ok"}'
    ping = client.post(
        "/api/github/webhook",
        content=ping_body,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(secret, ping_body),
        },
    )
    assert ping.status_code == 200
    assert ping.json()["event"] == "ping"

    push_payload = {
        "ref": "refs/heads/main",
        "after": "abc123def456",
        "repository": {"full_name": "example/my-next-app"},
        "command": "rm -rf /",
    }
    push_body = json.dumps(push_payload).encode("utf-8")
    push = client.post(
        "/api/github/webhook",
        content=push_body,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": _sign(secret, push_body),
        },
    )
    assert push.status_code == 200
    body = push.json()
    assert body["status"] == "QUEUED"
    assert body["queued"]
    assert "command" not in body

    deployments = client.get("/api/projects/my-next-app/deployments")
    assert deployments.status_code == 200
    rows = deployments.json()["deployments"]
    assert rows[0]["status"] == "QUEUED"
    assert rows[0]["commit_sha"] == "abc123def456"


def test_webhook_unknown_repository_and_branch(client: TestClient, tmp_env: Path) -> None:
    secret = "supersecret"
    _configure(tmp_env, secret)
    client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "branch": "main"},
    )

    unknown_repo = json.dumps(
        {
            "ref": "refs/heads/main",
            "after": "abc123",
            "repository": {"full_name": "someone/else"},
        }
    ).encode("utf-8")
    response = client.post(
        "/api/github/webhook",
        content=unknown_repo,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": _sign(secret, unknown_repo),
        },
    )
    assert response.status_code == 404

    unknown_branch = json.dumps(
        {
            "ref": "refs/heads/develop",
            "after": "abc123",
            "repository": {"full_name": "example/my-next-app"},
        }
    ).encode("utf-8")
    response = client.post(
        "/api/github/webhook",
        content=unknown_branch,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": _sign(secret, unknown_branch),
        },
    )
    assert response.status_code == 400


def test_list_repositories_uses_installation_token(tmp_env: Path, monkeypatch) -> None:
    _configure(tmp_env)

    def fake_call(method: str, path: str, token: str, json_body=None):
        if method == "GET" and path == "/app":
            return {"name": "VPS Deployer Dev"}
        if method == "POST" and path.endswith("/access_tokens"):
            return {"token": "ghs_test_token"}
        if method == "GET" and path == "/installation/repositories":
            return {
                "repositories": [
                    {"full_name": "example/my-next-app", "default_branch": "main"},
                    {"full_name": "example/my-api", "default_branch": "main"},
                ]
            }
        raise AssertionError(f"unexpected GitHub call {method} {path}")

    monkeypatch.setattr("vps_deployer.core.github.call_github", fake_call)
    from vps_deployer.core.github import list_accessible_repositories

    repos = list_accessible_repositories()
    assert repos[0]["repository"] == "example/my-next-app"
    assert repos[1]["repository"] == "example/my-api"


def test_github_status_endpoint(client: TestClient, tmp_env: Path) -> None:
    empty = client.get("/api/github/status")
    assert empty.status_code == 200
    assert empty.json()["configured"] is False
    _configure(tmp_env)
    configured = client.get("/api/github/status")
    assert configured.json()["configured"] is True
    assert configured.json()["app_id"] == "12345"
