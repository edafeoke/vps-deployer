from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from vps_deployer.core.config import get_settings
from vps_deployer.core.host import imported_apps, services_inventory
from vps_deployer.core.host_admin import (
    HostError,
    NginxHost,
    config_metadata,
    revision,
    service_action,
    service_inventory,
    validate_edit,
)

SITE = """server {
    listen 80;
    server_name legacy.example.com;
    location / {
        proxy_pass http://127.0.0.1:3000;
    }
}
"""


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "nginx"
    for name in ("sites-available", "sites-enabled", "conf.d", "snippets"):
        (root / name).mkdir(parents=True)
    site = root / "sites-available/legacy"
    site.write_text(SITE)
    (root / "sites-enabled/legacy").symlink_to(site)
    (root / "nginx.conf").write_text("events {}\nhttp {}\n")
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv == ["nginx", "-t"] and site.exists() and "broken" in site.read_text():
            return subprocess.CompletedProcess(argv, 1, "", "syntax error")
        loaded = [root / "nginx.conf", *(root / "sites-enabled").glob("*")]
        output = "\n".join(f"# configuration file {p.resolve()}:" for p in loaded)
        return subprocess.CompletedProcess(argv, 0, output, "syntax is ok")

    return NginxHost(root, runner, tmp_path / "backups", tmp_path / "lock"), calls


def test_inventory_deduplicates_and_reports_disabled(host):
    admin, _ = host
    (admin.root / "sites-available/offline").write_text(SITE)
    inventory = admin.inventory()
    legacy = next(r for r in inventory["configs"] if r["id"] == "sites-available/legacy")
    assert legacy["status"] == "ok"
    assert legacy["aliases"] == ["sites-available/legacy", "sites-enabled/legacy"]
    assert legacy["upstreams"] == ["http://127.0.0.1:3000"]
    offline = next(r for r in inventory["configs"] if r["id"].endswith("offline"))
    assert offline["status"] == "unchecked"
    assert not offline["enabled"]


def test_inventory_errors_are_not_reported_healthy(host):
    admin, _ = host
    path = admin.root / "sites-available/legacy"
    admin.runner = lambda argv: subprocess.CompletedProcess(argv, 1, "", f"error in {path}:5")
    rows = admin.inventory()["configs"]
    assert next(r for r in rows if r["id"].endswith("legacy"))["status"] == "error"
    assert not any(r["status"] == "ok" for r in rows)


def test_unincluded_config_is_not_reported_valid(host):
    admin, _ = host
    admin.runner = lambda argv: subprocess.CompletedProcess(argv, 0, "", "syntax is ok")
    row = next(r for r in admin.inventory()["configs"] if r["id"].endswith("legacy"))
    assert row["status"] == "unchecked"
    assert not row["included"]


def test_config_symlink_escape_and_traversal_rejected(host, tmp_path):
    admin, _ = host
    secret = tmp_path / "secret.conf"
    secret.write_text("SECRET_FILE_CONTENT")
    (admin.root / "sites-enabled/escape").symlink_to(secret)
    for path in ("../secret.conf", str(secret), "sites-enabled/escape"):
        with pytest.raises(HostError):
            admin.read(path)
    assert "SECRET_FILE_CONTENT" not in json.dumps(admin.inventory())


def test_save_revision_and_rollback(host):
    admin, calls = host
    before = admin.read("sites-available/legacy")
    payload = {
        "id": before["id"],
        "revision": before["revision"],
        "action": "save-reload",
        "content": SITE.replace("listen 80", "listen 8080"),
    }
    result = admin.action(payload)
    assert (admin.root / before["id"]).read_text() == payload["content"]
    assert Path(result["backup"]).is_dir()
    assert ["systemctl", "reload", "nginx"] in calls
    with pytest.raises(HostError, match="changed"):
        admin.action(payload)
    current = admin.read(before["id"])
    with pytest.raises(HostError, match="restored"):
        admin.action(
            {
                "id": before["id"],
                "revision": current["revision"],
                "action": "save",
                "content": current["content"].replace("legacy.example.com", "broken.example.com"),
            }
        )
    assert (admin.root / before["id"]).read_text() == current["content"]


def test_failed_reload_restores_original(host):
    admin, _ = host
    runner = admin.runner

    def fail_reload(argv):
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(argv, 1, "", "reload failed")
        return runner(argv)

    admin.runner = fail_reload
    with pytest.raises(HostError, match="restored"):
        admin.action(
            {"id": "sites-available/legacy", "revision": revision(SITE), "action": "disable"}
        )
    assert (admin.root / "sites-enabled/legacy").is_symlink()
    assert (admin.root / "sites-available/legacy").read_text() == SITE


def test_disable_enable_delete_keep_backup(host):
    admin, _ = host
    payload = {"id": "sites-available/legacy", "revision": revision(SITE)}
    admin.action({**payload, "action": "disable"})
    assert not (admin.root / "sites-enabled/legacy").exists()
    assert (admin.root / payload["id"]).exists()
    admin.action({**payload, "action": "enable"})
    assert (admin.root / "sites-enabled/legacy").is_symlink()
    deleted = admin.action({**payload, "action": "delete"})
    assert not (admin.root / payload["id"]).exists()
    admin.restore(Path(deleted["backup"]))
    assert (admin.root / payload["id"]).read_text() == SITE
    assert (admin.root / "sites-enabled/legacy").is_symlink()


def test_confd_disable_and_reenable(host):
    admin, _ = host
    path = admin.root / "conf.d/standalone.conf"
    path.write_text(SITE)
    disabled = admin.action(
        {"id": "conf.d/standalone.conf", "revision": revision(SITE), "action": "disable"}
    )
    assert disabled["id"] == "disabled-sites/conf.d/standalone.conf"
    assert not path.exists()
    assert any(r["id"] == disabled["id"] for r in admin.inventory()["configs"])
    enabled = admin.action({"id": disabled["id"], "revision": revision(SITE), "action": "enable"})
    assert path.read_text() == SITE
    assert enabled["id"] == "conf.d/standalone.conf"


@pytest.mark.parametrize(
    "injection",
    [
        "include /etc/evil.conf;",
        "load_module /tmp/evil.so;",
        "access_log /etc/sudoers;",
        "lua_code_cache off;",
        "perl_set $x test;",
        "root /etc;",
        "alias /root;",
        "proxy_pass http://remote.example.com;",
        "proxy_store /etc/shadow;",
    ],
)
def test_privileged_directive_injection_rejected(injection):
    with pytest.raises(HostError):
        validate_edit(SITE, SITE.replace("listen 80;", "listen 80;\n" + injection))


def test_preserves_existing_include_and_tls_directives():
    content = SITE.replace(
        "listen 80;",
        "listen 443 ssl;\ninclude /etc/nginx/snippets/tls.conf;\n"
        "ssl_certificate_key /etc/cloudflare/origin.key;",
    )
    validate_edit(content, content.replace("legacy.example.com", "new.example.com"))
    with pytest.raises(HostError):
        validate_edit(content, content.replace("origin.key", "other.key"))


def test_metadata_named_upstreams():
    data = config_metadata(
        "upstream backend { server 127.0.0.1:9000; }\n" + SITE.replace("127.0.0.1:3000", "backend")
    )
    assert data["upstream_groups"] == {"backend": ["127.0.0.1:9000"]}
    assert data["upstreams"] == ["http://backend"]


def system_runner(argv):
    if "list-units" in argv:
        output = json.dumps([{"unit": "legacy.service", "description": "Legacy app"}])
    elif "list-unit-files" in argv:
        output = "[]"
    elif "show" in argv:
        output = (
            "Id=legacy.service\nLoadState=loaded\nActiveState=active\nSubState=running\n"
            "MainPID=451\nUser=app\nWorkingDirectory=/srv/legacy\n"
        )
    elif argv[0] == "ss":
        output = 'LISTEN 0 128 127.0.0.1:3000 0.0.0.0:* users:(("node",pid=451,fd=10))\n'
    elif argv[0] == "ps":
        output = "451 1 app node\n"
    else:
        output = ""
    return subprocess.CompletedProcess(argv, 0, output, "")


def test_services_include_listeners_and_safe_process_names():
    result = service_inventory(system_runner)
    assert result["services"][0]["unit"] == "legacy.service"
    assert result["listeners"][0]["pids"] == [451]
    assert result["processes"][0]["command"] == "node"
    assert not result["errors"]


def test_service_actions_protect_infrastructure_and_validate_unit():
    calls = []

    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "Id=ssh.service\nLoadState=loaded\n", "")

    with pytest.raises(HostError, match="protected"):
        service_action({"unit": "alias.service", "action": "stop"}, runner)
    assert not any("stop" in call for call in calls)
    with pytest.raises(HostError, match="Invalid"):
        service_action({"unit": "bad;reboot.service", "action": "start"}, runner)
    assert (
        service_action({"unit": "legacy.service", "action": "stop"}, system_runner)["message"]
        == "legacy.service: stop"
    )


@pytest.fixture
def legacy_site(tmp_env):
    path = tmp_env / "nginx/sites-available/legacy"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SITE)
    enabled = tmp_env / "nginx/sites-enabled"
    enabled.mkdir()
    (enabled / "legacy").symlink_to(path)
    return path


def test_pages_editor_and_import(client, legacy_site):
    page = client.get("/nginx")
    assert page.status_code == 200
    assert "legacy.example.com" in page.text
    assert "Unmanaged" in page.text
    item = client.get("/api/host/nginx/config", params={"config": "sites-available/legacy"}).json()
    edited = SITE.replace("listen 80", "listen 8080")
    response = client.post(
        "/nginx/action",
        data={
            "config": item["id"],
            "revision": item["revision"],
            "action": "save",
            "content": edited.replace("\n", "\r\n"),
        },
    )
    assert response.status_code == 200
    assert "listen 8080" in response.text
    assert legacy_site.read_text() == edited
    imported = client.post("/nginx/adopt", data={"config": item["id"], "name": "legacy-app"})
    assert imported.status_code == 200
    assert "legacy-app" in imported.text
    assert imported_apps(get_settings())[0]["config_id"] == item["id"]
    assert legacy_site.read_text() == edited
    assert "legacy-app" in client.get("/projects").text
    assert "Imported app" in client.get("/nginx").text
    assert (
        client.post(
            "/api/host/import", json={"config": item["id"], "name": "duplicate"}
        ).status_code
        == 422
    )


def test_api_confirmation_and_origin_protection(client, legacy_site):
    payload = {"id": "sites-available/legacy", "revision": revision(SITE), "action": "delete"}
    assert client.post("/api/host/nginx/action", json=payload).status_code == 422
    assert legacy_site.exists()
    assert (
        client.post(
            "/api/host/nginx/action",
            json={**payload, "confirm": payload["id"]},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    result = client.post("/api/host/nginx/action", json={**payload, "confirm": payload["id"]})
    assert result.status_code == 200, result.text
    assert not legacy_site.exists()
    assert Path(result.json()["backup"]).exists()


def test_imported_domains_follow_saved_config(client, legacy_site):
    from vps_deployer.core.domains import claimed_hostnames

    response = client.post(
        "/api/host/import", json={"config": "sites-available/legacy", "name": "legacy-app"}
    )
    assert response.status_code == 200, response.text
    assert "legacy.example.com" in claimed_hostnames()
    response = client.post(
        "/api/host/nginx/action",
        json={
            "id": "sites-available/legacy",
            "revision": revision(SITE),
            "action": "save",
            "content": SITE.replace("legacy.example.com", "changed.example.com"),
        },
    )
    assert response.status_code == 200, response.text
    assert "changed.example.com" in claimed_hostnames()
    assert "legacy.example.com" not in claimed_hostnames()


def test_failed_form_keeps_unsaved_content(client, legacy_site):
    bad = SITE + "load_module /tmp/evil.so;\n"
    result = client.post(
        "/nginx/action",
        data={
            "config": "sites-available/legacy",
            "action": "save",
            "revision": revision(SITE),
            "content": bad,
        },
    )
    assert result.status_code == 422
    assert "load_module /tmp/evil.so" in result.text
    assert legacy_site.read_text() == SITE


def test_service_links_to_nginx(client, legacy_site, monkeypatch):
    from vps_deployer.core import host as module

    original = module._call

    def fake(action, payload, settings):
        return (
            service_inventory(system_runner)
            if action == "host-service-inventory"
            else original(action, payload, settings)
        )

    monkeypatch.setattr(module, "_call", fake)
    result = services_inventory()
    service = result["services"][0]
    assert service["listeners"] == ["127.0.0.1:3000"]
    assert service["configs"][0]["id"] == "sites-available/legacy"
    assert result["processes"][0]["configs"][0]["id"] == "sites-available/legacy"
    assert "legacy.service" in client.get("/services").text


def test_host_endpoints_require_public_login(client, tmp_env, legacy_site):
    from vps_deployer.core.dashboard_access import enable_dashboard_access

    enable_dashboard_access(hosts=["panel.example.com"], password="secretpass")
    for path in ("/api/host/nginx", "/api/host/services"):
        assert client.get(path, headers={"Host": "panel.example.com"}).status_code == 401


def test_installer_uses_isolated_root_owned_helper():
    root = Path(__file__).parents[1]
    installer = (root / "installer/install.sh").read_text()
    helper = (root / "packaging/helper/vps-deployer-helper").read_text()
    assert "/usr/bin/python3 -I /usr/local/libexec/vps-deployer-admin.py" in helper
    assert (
        'install -o root -g root -m 0644 "${VD_SOURCE}/src/vps_deployer/core/host_admin.py"'
        in installer
    )
