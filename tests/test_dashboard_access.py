from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_github_pem
from vps_deployer.core.config import get_settings
from vps_deployer.core.dashboard_access import (
    enable_dashboard_access,
    render_dashboard_nginx,
)
from vps_deployer.core.domains import DomainConflictError
from vps_deployer.core.github import configure_github
from vps_deployer.core.projects import ProjectCreate, create_project


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
