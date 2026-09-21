from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from vps_deployer.core.config import get_settings
from vps_deployer.core.nginx import render_nginx_site
from vps_deployer.core.projects import ProjectCreate, create_project
from vps_deployer.core.ssl import load_ssl_email, save_ssl_email
from vps_deployer.core.validation import APPS_ROOT
from vps_deployer.db.models import Domain, Project


def _project(runtime: str = "nextjs") -> Project:
    return Project(
        name="my-next-app",
        repository="example/my-next-app",
        branch="main",
        runtime=runtime,
        deployment_path="/var/www/apps/my-next-app",
        port=33101,
        service_name="vps-deployer-app-my-next-app",
    )


def test_render_proxy_site() -> None:
    domain = Domain(project_id=1, hostname="example.com", www_enabled=True)
    text = render_nginx_site(_project(), [domain], apps_root=APPS_ROOT)
    assert "# vps-deployer site: my-next-app" in text
    assert "server_name example.com www.example.com;" in text
    assert "listen 80;" in text
    assert "proxy_pass http://127.0.0.1:33101;" in text
    assert "root /var/www/certbot;" in text
    assert "ssl_certificate" not in text


def test_render_static_site() -> None:
    domain = Domain(project_id=1, hostname="example.com", www_enabled=False)
    text = render_nginx_site(_project("static"), [domain], apps_root=APPS_ROOT)
    assert "root /var/www/apps/my-next-app/current;" in text
    assert "try_files $uri $uri/ /index.html;" in text
    assert "proxy_pass" not in text


def test_add_list_remove_domain(tmp_env: Path, client: TestClient) -> None:
    created = client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "port": 33130},
    )
    assert created.status_code == 201
    added = client.post(
        "/api/projects/my-next-app/domains",
        json={"hostname": "example.com", "www": True},
    )
    assert added.status_code == 201, added.text
    assert added.json()["hostname"] == "example.com"
    assert added.json()["www"] is True
    listed = client.get("/api/projects/my-next-app/domains")
    assert listed.status_code == 200
    assert listed.json()["domains"][0]["hostname"] == "example.com"
    site = tmp_env / "nginx" / "vps-deployer-my-next-app.conf"
    assert site.is_file()
    assert "server_name example.com www.example.com;" in site.read_text(encoding="utf-8")
    shown = client.get("/api/projects/my-next-app")
    assert shown.json()["domain"] == "example.com"
    removed = client.delete("/api/projects/my-next-app/domains/example.com")
    assert removed.status_code == 200
    assert client.get("/api/projects/my-next-app/domains").json() == {"domains": []}
    assert not site.exists()
    assert client.get("/api/projects/my-next-app").json()["domain"] is None


def test_domain_conflict_and_invalid(tmp_env: Path, client: TestClient) -> None:
    client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "port": 33131},
    )
    client.post(
        "/api/projects",
        json={"name": "my-api", "repository": "example/my-api", "port": 33132},
    )
    assert (
        client.post(
            "/api/projects/my-next-app/domains",
            json={"hostname": "example.com", "www": True},
        ).status_code
        == 201
    )
    conflict = client.post(
        "/api/projects/my-api/domains",
        json={"hostname": "www.example.com"},
    )
    assert conflict.status_code == 409
    invalid = client.post(
        "/api/projects/my-next-app/domains",
        json={"hostname": "not a domain"},
    )
    assert invalid.status_code == 422
    missing = client.delete("/api/projects/my-next-app/domains/missing.example.com")
    assert missing.status_code == 404


def test_render_https_site() -> None:
    domain = Domain(project_id=1, hostname="example.com", www_enabled=True, ssl_enabled=True)
    text = render_nginx_site(_project(), [domain], apps_root=APPS_ROOT)
    assert "listen 443 ssl;" in text
    assert "ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;" in text
    assert "ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;" in text
    assert "return 301 https://$host$request_uri;" in text
    assert "proxy_pass http://127.0.0.1:33101;" in text


def test_enable_ssl_local(tmp_env: Path, client: TestClient) -> None:
    created = client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "port": 33134},
    )
    assert created.status_code == 201
    client.post("/api/projects/my-next-app/domains", json={"hostname": "example.com", "www": True})
    missing = client.post("/api/projects/missing-app/ssl")
    assert missing.status_code == 404
    enabled = client.post(
        "/api/projects/my-next-app/ssl",
        json={"email": "ops@example.com"},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["ssl"] is True
    assert enabled.json()["certificate"] == "example.com"
    status = client.get("/api/projects/my-next-app/ssl")
    assert status.status_code == 200
    assert status.json()["ssl"] is True
    site = (tmp_env / "nginx" / "vps-deployer-my-next-app.conf").read_text(encoding="utf-8")
    assert "listen 443 ssl;" in site
    assert (tmp_env / "ssl" / "example.com" / "fullchain.pem").is_file()
    assert (tmp_env / "ssl" / "example.com" / "privkey.pem").is_file()
    renewed = client.post("/api/ssl/renew")
    assert renewed.status_code == 200
    assert renewed.json()["renewed"] is True


def test_root_ssl_email_write_assigns_file_to_service_user(tmp_env: Path, monkeypatch) -> None:
    settings = get_settings()
    assert settings.config_dir is not None
    monkeypatch.setattr("vps_deployer.core.ssl.PRODUCTION_CONFIG_DIR", settings.config_dir)
    monkeypatch.setattr(
        "vps_deployer.core.ssl.pwd.getpwnam",
        lambda _name: SimpleNamespace(pw_uid=123, pw_gid=456),
    )
    monkeypatch.setattr("vps_deployer.core.ssl.os.geteuid", lambda: 0)
    ownership: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(
        "vps_deployer.core.ssl.os.chown",
        lambda path, uid, gid: ownership.append((Path(path), uid, gid)),
    )

    save_ssl_email("ops@example.com", settings)

    assert ownership == [(settings.config_dir / "ssl.json", 123, 456)]


def test_unreadable_ssl_email_does_not_break_status(tmp_env: Path, monkeypatch) -> None:
    settings = get_settings().model_copy(update={"ssl_email": None})
    assert settings.config_dir is not None
    path = settings.config_dir / "ssl.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"email":"ops@example.com"}\n', encoding="utf-8")
    original = Path.read_text

    def denied(current: Path, *args, **kwargs):
        if current == path:
            raise PermissionError("denied")
        return original(current, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    assert load_ssl_email(settings) is None


def test_ssl_requires_domain(tmp_env: Path, client: TestClient) -> None:
    client.post(
        "/api/projects",
        json={"name": "my-api", "repository": "example/my-api", "port": 33135},
    )
    response = client.post("/api/projects/my-api/ssl", json={"email": "ops@example.com"})
    assert response.status_code == 409


def test_create_project_with_domain(tmp_env: Path) -> None:
    project = create_project(
        ProjectCreate(
            name="my-site",
            repository="example/my-site",
            runtime="static",
            port=33133,
            domain="example.com",
        )
    )
    assert project.domain == "example.com"
    site = tmp_env / "nginx" / "vps-deployer-my-site.conf"
    assert site.is_file()
    assert "root " in site.read_text(encoding="utf-8")
