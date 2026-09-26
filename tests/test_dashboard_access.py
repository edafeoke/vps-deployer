from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import make_github_pem
from vps_deployer.core import dashboard_access
from vps_deployer.core.config import get_settings
from vps_deployer.core.dashboard_access import (
    enable_dashboard_access,
    render_dashboard_nginx,
    set_dashboard_password,
)
from vps_deployer.core.domains import DomainConflictError
from vps_deployer.core.github import configure_github
from vps_deployer.core.projects import ProjectCreate, create_project


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "[]",
        "{}",
        '{"hosts": [], "password_hash": "", "session_secret": "secret"}',
        '{"hosts": [], "password_hash": "hash", "session_secret": ""}',
    ],
)
def test_invalid_auth_state_blocks_panel_and_api(
    tmp_env: Path,
    client: TestClient,
    payload: str,
) -> None:
    dashboard_access.dashboard_state_path().write_text(payload)
    for path in ("/", "/api/status", "/login", "/settings"):
        assert client.get(path, follow_redirects=False).status_code == 503
    assert client.get("/health").status_code == 200


def test_unreadable_auth_state_fails_closed(
    tmp_env: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_github(
        app_id="12345",
        private_key=make_github_pem(),
        webhook_secret="supersecret-webhook",
        settings=get_settings(),
    )
    set_dashboard_password("secretpass")
    original = Path.read_text

    def unreadable(path: Path, *args, **kwargs):
        if path == dashboard_access.dashboard_state_path():
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    for path in ("/", "/api/status", "/login"):
        assert client.get(path, follow_redirects=False).status_code == 503
    assert client.post("/api/projects", json={}).status_code == 503
    assert client.post("/api/github/webhook", content=b"{}").status_code == 401


def test_password_change_locks_panel_and_invalidates_session(
    tmp_env: Path,
    client: TestClient,
) -> None:
    assert client.get("/").status_code == 200
    set_dashboard_password("secretpass")
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/api/status").status_code == 401
    assert (
        client.post("/login", data={"password": "secretpass"}, follow_redirects=False).status_code
        == 303
    )
    assert client.get("/").status_code == 200
    set_dashboard_password("replacementpass")
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/api/status").status_code == 401
    assert dashboard_access.dashboard_state_path().stat().st_mode & 0o777 == 0o600


def test_root_password_write_assigns_service_ownership_before_publish(
    tmp_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(dashboard_access, "PRODUCTION_CONFIG_DIR", settings.config_dir)
    monkeypatch.setattr(dashboard_access.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        dashboard_access.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=123, pw_gid=456)
    )
    assigned = []
    monkeypatch.setattr(
        dashboard_access.os, "fchown", lambda fd, uid, gid: assigned.append((uid, gid))
    )
    original = dashboard_access.os.replace

    def publish(source, destination):
        assert assigned == [(123, 456)]
        assert Path(source).stat().st_mode & 0o777 == 0o600
        original(source, destination)

    monkeypatch.setattr(dashboard_access.os, "replace", publish)
    set_dashboard_password("secretpass", settings)
    assert dashboard_access.authenticate_dashboard("secretpass", settings)


def test_failed_atomic_write_preserves_previous_password(
    tmp_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_dashboard_password("secretpass")
    previous = dashboard_access.dashboard_state_path().read_bytes()

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(dashboard_access.os, "replace", fail)
    with pytest.raises(OSError):
        set_dashboard_password("replacementpass")
    assert dashboard_access.dashboard_state_path().read_bytes() == previous
    assert not list(dashboard_access.dashboard_state_path().parent.glob(".dashboard-*"))


def test_render_dashboard_nginx_hostname_and_ip() -> None:
    text = render_dashboard_nginx(["panel.example.com", "203.0.113.10"])
    assert "# vps-deployer site: dashboard" in text
    assert "server_name panel.example.com 203.0.113.10;" in text
    assert "proxy_pass http://127.0.0.1:5100;" in text
    assert "root /var/www/certbot;" in text
    assert "ssl_certificate" not in text


def test_render_dashboard_nginx_https_keeps_ip_on_http() -> None:
    text = render_dashboard_nginx(
        ["panel.example.com", "203.0.113.10"],
        ssl=True,
        ssl_cert_dir=Path("/etc/letsencrypt/live/panel.example.com"),
    )
    assert "listen 443 ssl;" in text
    assert "server_name panel.example.com;" in text
    assert "server_name 203.0.113.10;" in text
    assert "return 301 https://$host$request_uri;" in text
    assert "ssl_certificate /etc/letsencrypt/live/panel.example.com/fullchain.pem;" in text


def test_enable_rejects_project_hostname(tmp_env: Path) -> None:
    create_project(
        ProjectCreate(name="my-next-app", repository="example/my-next-app", domain="example.com"),
        get_settings(),
    )
    with pytest.raises(DomainConflictError):
        enable_dashboard_access(
            hosts=["example.com"],
            password="secretpass",
            settings=get_settings(),
        )


def test_public_host_requires_login(tmp_env: Path, client: TestClient) -> None:
    enable_dashboard_access(
        hosts=["panel.example.com"],
        password="secretpass",
        settings=get_settings(),
    )
    local = client.get("/", follow_redirects=False)
    assert local.status_code == 303
    assert "/login" in local.headers["location"]
    blocked = client.get("/", headers={"Host": "panel.example.com"}, follow_redirects=False)
    assert blocked.status_code == 303
    assert "/login" in blocked.headers["location"]
    api = client.get("/api/status", headers={"Host": "panel.example.com"})
    assert api.status_code == 401
    login = client.post(
        "/login",
        data={"password": "secretpass", "next": "/"},
        headers={"Host": "panel.example.com"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    opened = client.get("/", headers={"Host": "panel.example.com"})
    assert opened.status_code == 200
    assert "This VPS" in opened.text
    local_login = client.post(
        "/login",
        data={"password": "secretpass", "next": "/"},
        follow_redirects=False,
    )
    assert local_login.status_code == 303
    assert client.get("/").status_code == 200


def test_public_webhook_still_uses_hmac(tmp_env: Path, client: TestClient) -> None:
    configure_github(
        app_id="12345",
        private_key=make_github_pem(),
        webhook_secret="supersecret-webhook",
        settings=get_settings(),
    )
    enable_dashboard_access(
        hosts=["panel.example.com"],
        password="secretpass",
        settings=get_settings(),
    )
    missing = client.post(
        "/api/github/webhook",
        content=b"{}",
        headers={"Host": "panel.example.com"},
    )
    assert missing.status_code == 401
