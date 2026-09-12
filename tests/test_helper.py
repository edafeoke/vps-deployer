from __future__ import annotations

import subprocess
from pathlib import Path

from vps_deployer.core.dashboard_access import render_dashboard_nginx
from vps_deployer.core.nginx import render_nginx_site
from vps_deployer.core.units import render_app_unit
from vps_deployer.core.validation import APPS_ROOT
from vps_deployer.db.models import Domain, Project

HELPER = Path(__file__).resolve().parents[1] / "packaging" / "helper" / "vps-deployer-helper"


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HELPER), *args],
        check=False,
        capture_output=True,
        text=True,
        input=stdin,
    )


def test_helper_rejects_unknown_action() -> None:
    result = _run("rm")
    assert result.returncode == 2
    assert "rejected" in result.stderr


def test_helper_rejects_invalid_service_name() -> None:
    result = _run("service-status", "../etc/passwd")
    assert result.returncode == 2
    result = _run("service-status", "unit;reboot")
    assert result.returncode == 2
    result = _run("service-status", "unit$(id)")
    assert result.returncode == 2
    result = _run("service-status", "sshd.service")
    assert result.returncode == 2
    assert "outside this installation" in result.stderr


def test_helper_missing_action() -> None:
    result = _run()
    assert result.returncode == 1
    assert "Usage" in result.stdout


def test_helper_rejects_invalid_app_project() -> None:
    result = _run("app-start", "../etc/passwd")
    assert result.returncode == 2
    result = _run("app-stop", "app;reboot")
    assert result.returncode == 2
    result = _run("app-restart", "app$(id)")
    assert result.returncode == 2
    result = _run("app-unit-remove", "MyApp")
    assert result.returncode == 2


def test_helper_app_unit_check_accepts_rendered_unit() -> None:
    unit = render_app_unit(
        project="my-next-app",
        port=33101,
        workdir=Path("/var/www/apps/my-next-app/current"),
        command=["npm", "start"],
    )
    result = _run("app-unit-check", "my-next-app", stdin=unit)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_helper_app_unit_check_rejects_shell_and_root() -> None:
    unit = render_app_unit(
        project="my-next-app",
        port=33101,
        workdir=Path("/var/www/apps/my-next-app/current"),
        command=["npm", "start"],
    )
    evil = unit.replace("User=vps-deployer", "User=root")
    assert _run("app-unit-check", "my-next-app", stdin=evil).returncode == 2
    shell = unit.replace("ExecStart=npm start", "ExecStart=/bin/bash -c reboot")
    assert _run("app-unit-check", "my-next-app", stdin=shell).returncode == 2
    escaped = unit.replace("/var/www/apps/my-next-app/current", "/etc/passwd")
    assert _run("app-unit-check", "my-next-app", stdin=escaped).returncode == 2
    envfile = unit.replace(
        "EnvironmentFile=-/var/www/apps/my-next-app/shared/env",
        "EnvironmentFile=-/var/www/apps/my-next-app/shared/env\nEnvironmentFile=/etc/shadow",
    )
    assert _run("app-unit-check", "my-next-app", stdin=envfile).returncode == 2


def _site() -> str:
    project = Project(
        name="my-next-app",
        repository="example/my-next-app",
        branch="main",
        runtime="nextjs",
        deployment_path="/var/www/apps/my-next-app",
        port=33101,
        service_name="vps-deployer-app-my-next-app",
    )
    domain = Domain(project_id=1, hostname="example.com", www_enabled=True)
    return render_nginx_site(project, [domain], apps_root=APPS_ROOT)


def test_helper_nginx_site_check_accepts_rendered_site() -> None:
    result = _run("nginx-site-check", "my-next-app", stdin=_site())
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_helper_nginx_site_check_rejects_unsafe_proxy_and_root() -> None:
    site = _site()
    evil = site.replace("http://127.0.0.1:33101", "http://evil.example")
    assert _run("nginx-site-check", "my-next-app", stdin=evil).returncode == 2
    include = site.replace("server {", "include /etc/nginx/evil.conf;\nserver {")
    assert _run("nginx-site-check", "my-next-app", stdin=include).returncode == 2
    rewrite = site.replace(
        "    location / {",
        "    rewrite ^ http://evil.example/ permanent;\n    location / {",
    )
    assert _run("nginx-site-check", "my-next-app", stdin=rewrite).returncode == 2
    assert _run("nginx-site-install", "../etc").returncode == 2
    port = site.replace("http://127.0.0.1:33101", "http://127.0.0.1:5100")
    assert _run("nginx-site-check", "my-next-app", stdin=port).returncode == 2


def test_helper_nginx_site_check_accepts_https() -> None:
    project = Project(
        name="my-next-app",
        repository="example/my-next-app",
        branch="main",
        runtime="nextjs",
        deployment_path="/var/www/apps/my-next-app",
        port=33101,
        service_name="vps-deployer-app-my-next-app",
    )
    domain = Domain(project_id=1, hostname="example.com", www_enabled=True, ssl_enabled=True)
    site = render_nginx_site(project, [domain], apps_root=APPS_ROOT)
    result = _run("nginx-site-check", "my-next-app", stdin=site)
    assert result.returncode == 0, result.stderr


def test_helper_dashboard_site_check_accepts_hostname_and_ip() -> None:
    site = render_dashboard_nginx(["panel.example.com", "203.0.113.10"])
    result = _run("dashboard-site-check", stdin=site)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    evil = site.replace("http://127.0.0.1:5100", "http://127.0.0.1:33101")
    assert _run("dashboard-site-check", stdin=evil).returncode == 2
    root = site.replace("root /var/www/certbot;", "root /var/www/apps/my-next-app;")
    assert _run("dashboard-site-check", stdin=root).returncode == 2


def test_helper_ssl_issue_rejects_invalid_input() -> None:
    assert _run("ssl-issue", "not-an-email", "example.com", "example.com").returncode == 2
    assert _run("ssl-issue", "ops@example.com", "../etc", "example.com").returncode == 2
    assert _run("ssl-issue", "ops@example.com", "other.com", "example.com").returncode == 2
    missing = _run("ssl-issue", "ops@example.com", "example.com", "example.com")
    assert missing.returncode in {2, 4}
