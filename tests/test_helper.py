from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

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


def test_helper_accepts_external_paths_and_tuning() -> None:
    site = (
        _site()
        .replace("32m;", "64m;")
        .replace(
            "proxy_http_version 1.1;", "proxy_http_version 1.1;\n        proxy_read_timeout 120s;"
        )
        .replace(
            "    listen 80;",
            "    listen 443 ssl;\n"
            "    ssl_certificate /etc/ssl/vps-deployer/my-next-app/origin.pem;\n"
            "    ssl_certificate_key /etc/ssl/vps-deployer/my-next-app/origin.key;",
        )
    )
    assert _run("nginx-site-check", "my-next-app", stdin=site).returncode == 0
    wrong = site.replace("/my-next-app/origin", "/other-app/origin")
    assert _run("nginx-site-check", "my-next-app", stdin=wrong).returncode == 2
    assert _run("nginx-site-read", "../etc").returncode == 2
    assert (
        _run(
            "ssl-external-check", "my-next-app", "/etc/passwd", "/etc/shadow", "example.com"
        ).returncode
        == 2
    )
    injected = _site().replace(
        "root /var/www/certbot;", "root /var/www/apps/my-next-app/a; include /etc/evil;"
    )
    assert _run("nginx-site-check", "my-next-app", stdin=injected).returncode == 2


@pytest.mark.parametrize("failure", ["test", "reload", "none"])
@pytest.mark.parametrize("existing", [True, False])
def test_helper_transaction_restores_files_and_symlinks(tmp_path, failure, existing):
    # Run the real helper logic against an isolated filesystem and fake Nginx.
    root = tmp_path / "nginx"
    for subdir in ("sites-available", "sites-enabled", "conf.d"):
        (root / subdir).mkdir(parents=True)
    site = root / "sites-available/vps-deployer-my-next-app.conf"
    enabled = root / "sites-enabled/vps-deployer-my-next-app.conf"
    if existing:
        site.write_text("old site\n")
        enabled.symlink_to(site)
    bins = tmp_path / "bin"
    bins.mkdir()
    nginx = bins / "nginx"
    nginx.write_text(
        "#!/bin/bash\n"
        'if grep -q "client_max_body_size" "$TEST_SITE" 2>/dev/null; then\n'
        '  [[ "$TEST_FAILURE" == test && "$1" == -t ]] && exit 1\n'
        '  [[ "$TEST_FAILURE" == reload && "$1" == -s ]] && exit 1\n'
        "fi\nexit 0\n"
    )
    nginx.chmod(0o755)
    for command, code in (("flock", 0), ("systemctl", 1)):
        mock = bins / command
        mock.write_text(f"#!/bin/sh\nexit {code}\n")
        mock.chmod(0o755)
    script = (
        HELPER.read_text()
        .replace("/etc/nginx", str(root))
        .replace("/run/lock/vps-deployer-nginx.lock", str(tmp_path / "lock"))
    )
    result = subprocess.run(
        ["bash", "-c", script, "helper", "nginx-site-install", "my-next-app"],
        input=_site(),
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{bins}:{os.environ['PATH']}",
            "TEST_SITE": str(site),
            "TEST_FAILURE": failure,
        },
        check=False,
    )
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert "client_max_body_size" in site.read_text()
        assert enabled.resolve() == site
    else:
        assert result.returncode == 3, result.stderr
        assert "previous site restored" in result.stderr
        assert site.exists() == existing
        assert enabled.is_symlink() == existing
        if existing:
            assert site.read_text() == "old site\n"
            assert enabled.resolve() == site
