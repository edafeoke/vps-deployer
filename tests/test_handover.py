from __future__ import annotations

import subprocess
from inspect import unwrap
from pathlib import Path

import pytest

from test_engine import _init_repo
from test_host import SITE
from test_host import host as host_fixture
from test_site_config import certificate_files, create_site
from vps_deployer.core.config import get_settings
from vps_deployer.core.engine import execute_deployment
from vps_deployer.core.handover import queue_handover
from vps_deployer.core.host import adopt_site, imported_apps, nginx_config
from vps_deployer.core.host_admin import HostError, handover_content, import_certificate, revision
from vps_deployer.core.nginx import nginx_status
from vps_deployer.core.projects import ProjectCreate, create_project
from vps_deployer.core.site_config import load_site_config

STATIC = (
    "server {\n listen 80;\n server_name legacy.example.com;\n"
    " root /srv/old;\n client_max_body_size 80m;\n}\n"
)


@pytest.fixture
def host(tmp_path):
    return unwrap(host_fixture)(tmp_path)


def setup_static(tmp_env, *, fail=False):
    _init_repo(tmp_env / "git", "example/replacement", fail_build=fail)
    create_project(
        ProjectCreate(name="replacement", repository="example/replacement", runtime="static")
    )
    path = tmp_env / "nginx/sites-available/legacy"
    path.parent.mkdir(parents=True)
    path.write_text(STATIC)
    enabled = tmp_env / "nginx/sites-enabled"
    enabled.mkdir()
    (enabled / "legacy").symlink_to(path)
    return path


def test_external_files_are_copied_without_overwriting_sources(client, tmp_env):
    create_site(client)
    files = certificate_files(tmp_env / "elsewhere")
    source_bytes = {k: Path(v).read_bytes() for k, v in files.items()}
    first = client.post("/api/projects/my-app/ssl/external", json=files)
    assert first.status_code == 200, first.text
    for field in files:
        copied = Path(first.json()[field])
        assert copied.parent == tmp_env / "ssl/my-app"
        assert copied.read_bytes() == source_bytes[field]
        assert Path(files[field]).read_bytes() == source_bytes[field]
    second = client.post("/api/projects/my-app/ssl/external", json=files)
    assert second.status_code == 200
    assert first.json()["certificate_key"] != second.json()["certificate_key"]
    assert Path(first.json()["certificate_key"]).exists()


def test_certificate_destination_symlink_rejected(tmp_env):
    files = certificate_files(tmp_env / "source")
    base = tmp_env / "target"
    base.mkdir()
    outside = tmp_env / "outside"
    outside.mkdir()
    (base / "my-app").symlink_to(outside)
    with pytest.raises(HostError, match="symlink"):
        import_certificate({**files, "project": "my-app", "hostnames": ["example.com"]}, base)
    assert list(outside.iterdir()) == []


def test_deploy_and_transfer_static_website(client, tmp_env):
    path = setup_static(tmp_env)
    adopt_site("sites-available/legacy", "old-site")
    queued = queue_handover("sites-available/legacy", "replacement", [], revision(STATIC))
    assert path.read_text() == STATIC
    result = execute_deployment(queued["deployment"]["id"])
    assert result.status == "SUCCESS", result.error_message
    assert f"root {tmp_env}/apps/replacement/current;" in path.read_text()
    assert "client_max_body_size 80m;" in path.read_text()
    assert nginx_config("sites-available/legacy")["project"] == "replacement"
    assert not imported_apps()
    domains = client.get("/api/projects/replacement/domains").json()["domains"]
    assert domains[0]["hostname"] == "legacy.example.com"
    assert (
        load_site_config("replacement", get_settings())["host_config_id"]
        == "sites-available/legacy"
    )
    assert "80m" in str(nginx_status("replacement")["content"])
    assert client.post("/api/projects/replacement/nginx").status_code == 200
    assert "80m" in path.read_text()
    saved = client.put(
        "/api/projects/replacement/nginx", json={"content": path.read_text().replace("80m", "90m")}
    )
    assert saved.status_code == 200, saved.text
    assert "90m" in path.read_text()
    assert client.delete("/api/projects/replacement/nginx").status_code == 422
    page = client.get("/projects/replacement").text
    assert "Open host editor and website controls" in page
    assert "Reset to generated config" not in page
    assert "Let's Encrypt email" not in page
    bad = client.put(
        "/api/projects/replacement/nginx",
        json={"content": path.read_text() + "load_module /tmp/evil.so;\n"},
    )
    assert bad.status_code >= 400
    assert "load_module" not in path.read_text()


@pytest.mark.parametrize("failure", ["build", "stale"])
def test_failed_handover_leaves_old_website(client, tmp_env, failure):
    path = setup_static(tmp_env, fail=failure == "build")
    queued = queue_handover("sites-available/legacy", "replacement", [], revision(STATIC))
    if failure == "stale":
        path.write_text(STATIC + "# edited during build\n")
    before = path.read_text()
    result = execute_deployment(queued["deployment"]["id"])
    assert result.status == "FAILED"
    assert path.read_text() == before
    assert not load_site_config("replacement", get_settings()).get("pending_handover")
    assert not client.get("/api/projects/replacement/domains").json()["domains"]


def test_confirmation_and_stale_revision(client, tmp_env):
    setup_static(tmp_env)
    payload = {
        "config": "sites-available/legacy",
        "project": "replacement",
        "revision": revision(STATIC),
        "confirm": "",
    }
    assert client.post("/api/host/handover", json=payload).status_code == 422
    payload["confirm"] = payload["config"]
    payload["revision"] = "stale"
    assert client.post("/api/host/handover", json=payload).status_code == 422
    payload["revision"] = revision(STATIC)
    assert (
        client.post(
            "/api/host/handover", json=payload, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/host/handover", json=payload).status_code == 200
    assert client.post("/api/host/handover", json=payload).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        "location /api { proxy_pass http://127.0.0.1:4000; }",
        "fastcgi_pass unix:/run/php.sock;",
        "alias /srv/uploads;",
        "upstream apps { server 127.0.0.1:3000; }",
    ],
)
def test_ambiguous_routes_rejected(extra):
    with pytest.raises(HostError):
        handover_content(SITE + extra, "replacement", 33001, "node", Path("/var/www/apps"))


@pytest.mark.parametrize("fail", ["", "reload", "stop"])
def test_helper_switches_before_stopping_and_recovers(host, tmp_path, fail):
    admin, calls = host
    original = admin.runner
    active = True
    stopped = False
    first_reload = True

    def runner(argv):
        nonlocal active, stopped, first_reload
        if argv[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                "Id=legacy.service\nLoadState=loaded\nActiveState="
                + ("active" if active else "inactive")
                + "\n",
                "",
            )
        if argv[:2] == ["systemctl", "reload"] and first_reload:
            first_reload = False
            assert "33001" in (admin.root / "sites-available/legacy").read_text()
            if fail == "reload":
                return subprocess.CompletedProcess(argv, 1, "", "reload failed")
        if argv[:2] == ["systemctl", "stop"]:
            assert not first_reload
            stopped, active = True, False
            if fail == "stop":
                return subprocess.CompletedProcess(argv, 1, "", "stop failed")
        if argv[:2] == ["systemctl", "start"]:
            active = True
        return original(argv)

    admin.runner = runner
    payload = {
        "id": "sites-available/legacy",
        "revision": revision(SITE),
        "project": "replacement",
        "runtime": "node",
        "port": 33001,
        "units": ["legacy.service"],
    }
    if fail:
        with pytest.raises(HostError, match="restored"):
            admin.handover(payload)
        assert (admin.root / payload["id"]).read_text() == SITE
        assert active
        assert stopped == (fail == "stop")
    else:
        result = admin.handover(payload)
        assert stopped and not active
        assert Path(result["backup"]).exists()
        admin.rollback_handover({"backup": result["backup"]})
        assert active
        assert (admin.root / payload["id"]).read_text() == SITE


def test_privileged_handover_rejects_protected_service(host):
    admin, _ = host
    admin.runner = lambda argv: subprocess.CompletedProcess(
        argv, 0, "Id=ssh.service\nLoadState=loaded\nActiveState=active\n", ""
    )
    with pytest.raises(HostError, match="infrastructure"):
        admin.handover(
            {
                "id": "sites-available/legacy",
                "revision": revision(SITE),
                "project": "replacement",
                "runtime": "node",
                "port": 33001,
                "units": ["alias.service"],
            }
        )
    assert (admin.root / "sites-available/legacy").read_text() == SITE


def test_transferred_tls_is_copied_and_can_be_renewed(client, tmp_env):
    path = setup_static(tmp_env)
    files = certificate_files(tmp_env / "source", hosts=["legacy.example.com"])
    original = STATIC.replace(
        "listen 80;",
        "listen 443 ssl;\n ssl_certificate "
        + files["certificate"]
        + ";\n ssl_certificate_key "
        + files["certificate_key"]
        + ";",
    )
    path.write_text(original)
    queued = queue_handover("sites-available/legacy", "replacement", [], revision(original))
    result = execute_deployment(queued["deployment"]["id"])
    assert result.status == "SUCCESS", result.error_message
    state = load_site_config("replacement", get_settings())
    assert Path(state["certificate"]).parent == tmp_env / "ssl/replacement"
    assert Path(state["certificate_key"]).stat().st_mode & 0o777 == 0o600
    assert state["certificate"] in path.read_text()
    renewed = client.post("/api/projects/replacement/ssl/external", json=files)
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["certificate"] != state["certificate"]
    assert renewed.json()["certificate"] in path.read_text()
    assert "client_max_body_size 80m;" in path.read_text()


def test_metadata_write_failure_restores_original_website(client, tmp_env, monkeypatch):
    from vps_deployer.core import handover

    path = setup_static(tmp_env)
    queued = queue_handover("sites-available/legacy", "replacement", [], revision(STATIC))
    save = handover.save_site_config

    def fail_once(name, state, settings):
        if state.get("host_config_id"):
            raise OSError("Simulated metadata storage failure")
        return save(name, state, settings)

    monkeypatch.setattr(handover, "save_site_config", fail_once)
    result = execute_deployment(queued["deployment"]["id"])
    assert result.status == "FAILED"
    assert path.read_text() == STATIC
    assert not client.get("/api/projects/replacement/domains").json()["domains"]


def test_handover_cli_queues_confirmed_request(client, tmp_env, monkeypatch):
    from typer.testing import CliRunner

    from test_cli import _proxy_api
    from vps_deployer.cli.main import app

    setup_static(tmp_env)
    monkeypatch.setattr("vps_deployer.cli.main.api_request", _proxy_api(client))
    result = CliRunner().invoke(
        app, ["nginx", "handover", "replacement", "--config", "sites-available/legacy", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "queued" in result.output


def test_shared_old_service_cannot_be_stopped(client, tmp_env, monkeypatch):
    from vps_deployer.core import handover

    path = setup_static(tmp_env)
    path.write_text(SITE)
    create_project(ProjectCreate(name="new-node", repository="example/new-node", runtime="node"))
    config = nginx_config("sites-available/legacy")
    monkeypatch.setattr(
        handover,
        "services_inventory",
        lambda _: {
            "services": [
                {
                    "unit": "legacy.service",
                    "protected": False,
                    "project": None,
                    "configs": [config, {"id": "sites-available/another", "enabled": True}],
                }
            ]
        },
    )
    with pytest.raises(HostError, match="other enabled websites"):
        queue_handover(config["id"], "new-node", ["legacy.service"], revision(SITE))
    assert path.read_text() == SITE
