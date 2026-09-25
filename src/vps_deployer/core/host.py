from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import quote

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.helper import HelperError, require_helper
from vps_deployer.core.host_admin import HostError, NginxHost, revision
from vps_deployer.core.nginx import save_nginx_config, site_filename
from vps_deployer.core.projects import list_projects
from vps_deployer.core.site_config import load_site_config, save_site_config, site_mutation
from vps_deployer.core.validation import validate_project_name


def _local_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, 0, "", "Local preview: no Nginx daemon test/reload")


def _call(action: str, payload: dict | None, settings: Settings) -> dict[str, Any]:
    if settings.nginx_dir is not None and action.startswith("host-nginx"):
        assert settings.data_dir is not None
        host = NginxHost(
            settings.nginx_dir,
            _local_command,
            settings.data_dir / "nginx-backups",
            settings.data_dir / "nginx.lock",
        )
        payload = payload or {}
        if action == "host-nginx-inventory":
            result = host.inventory()
            result["test"]["ok"] = None
            for row in result["configs"]:
                row["status"] = "unchecked"
            result["local"] = True
            return result
        if action == "host-nginx-read":
            return {**host.read(payload["id"]), "local": True}
        return {
            **host.action(payload),
            "message": "Local preview updated; no daemon test/reload",
            "local": True,
        }
    try:
        response = require_helper(
            action, settings=settings, stdin=json.dumps(payload) if payload is not None else None
        )
        return json.loads(response.stdout)
    except (HelperError, ValueError) as exc:
        raise HostError(str(exc)) from exc


def _imports_path(settings: Settings) -> Path:
    assert settings.config_dir is not None
    return settings.config_dir / "imported-apps.json"


def imported_apps(settings: Settings | None = None) -> list[dict]:
    path = _imports_path(settings or get_settings())
    return json.loads(path.read_text()) if path.exists() else []


def _save_imports(rows: list[dict], settings: Settings):
    path = _imports_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        temp = Path(file.name)
        try:
            json.dump(rows, file)
            file.flush()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def nginx_inventory(settings: Settings | None = None) -> dict:
    current = settings or get_settings()
    try:
        result = _call("host-nginx-inventory", None, current)
    except HostError as exc:
        return {"configs": [], "test": {"ok": None, "detail": str(exc)}, "error": str(exc)}
    projects = {site_filename(p.name): p.name for p in list_projects(current)}
    imports = {row["config_id"]: row for row in imported_apps(current)}
    for row in result["configs"]:
        row["url"] = "/nginx/config?config=" + quote(row["id"], safe="")
        row["project"] = projects.get(Path(row["id"]).name)
        adopted = imports.get(row["id"])
        row["imported"] = adopted["name"] if adopted else None
        row["ownership"] = "project" if row["project"] else "imported" if adopted else "unmanaged"
    return result


def nginx_config(config_id: str, settings: Settings | None = None) -> dict:
    current = settings or get_settings()
    row = _call("host-nginx-read", {"id": config_id}, current)
    owner = next((r for r in nginx_inventory(current)["configs"] if r["id"] == row["id"]), {})
    return {**row, **{k: owner.get(k) for k in ("url", "project", "imported", "ownership")}}


@site_mutation
def nginx_action(payload: dict, settings: Settings | None = None) -> dict:
    current = settings or get_settings()
    action = payload.get("action")
    if action in {"test", "reload"}:
        return _call("host-nginx-action", payload, current)
    item = nginx_config(str(payload.get("id", "")), current)
    project = item.get("project")
    if project and action in {"save", "save-reload"}:
        if revision(item["content"]) != payload.get("revision"):
            raise HostError("Config changed since you opened it. Reload before saving.")
        save_nginx_config(project, str(payload.get("content", "")), current)
        return {
            "message": "Project config saved and applied; override persists across deployments",
            "id": item["id"],
            "reloaded": current.nginx_dir is None,
        }
    result = _call("host-nginx-action", payload, current)
    if project and action in {"disable", "delete", "enable"}:
        state = load_site_config(project, current)
        if action == "enable":
            state.pop("disabled", None)
        else:
            state["disabled"] = "true"
        save_site_config(project, state, current)
    rows = imported_apps(current)
    changed = False
    for row in rows:
        if row["config_id"] == item["id"]:
            row["config_id"] = result.get("id", item["id"])
            row["deleted"] = action == "delete"
            if action in {"save", "save-reload"}:
                from vps_deployer.core.host_admin import config_metadata

                metadata = config_metadata(payload.get("content", ""))
                row["domains"], row["roots"] = metadata["domains"], metadata["roots"]
            changed = True
    if changed:
        _save_imports(rows, current)
    return result


def services_inventory(settings: Settings | None = None) -> dict:
    current = settings or get_settings()
    result: dict[str, Any]
    try:
        result = _call("host-service-inventory", None, current)
    except HostError as exc:
        result = {"services": [], "listeners": [], "processes": [], "errors": [str(exc)]}
    configs = nginx_inventory(current)["configs"]
    project_units = {
        p.service_name + ("" if p.service_name.endswith(".service") else ".service"): p.name
        for p in list_projects(current)
    }
    imports = imported_apps(current)
    by_unit = {row["unit"]: row for row in result["services"]}
    for service in result["services"]:
        pids = {service["pid"]} | {
            p["pid"] for p in result["processes"] if p.get("unit") == service["unit"]
        }
        service["listeners"] = [
            listener["address"]
            for listener in result["listeners"]
            if pids.intersection(listener["pids"])
        ]
        ports = {
            address.rsplit(":", 1)[-1]
            for address in service["listeners"]
            if not address.startswith("unix:")
        }
        sockets = {address for address in service["listeners"] if address.startswith("unix:")}
        explicit = {a["config_id"] for a in imports if a.get("unit") == service["unit"]}
        service["configs"] = [
            c
            for c in configs
            if c["id"] in explicit
            or any(target in sockets for target in c.get("upstream_targets", c["upstreams"]))
            or any(
                re.search(
                    r"(?:127\.0\.0\.1|localhost|\[::1\]):(" + "|".join(ports) + r")(?:/|$)",
                    upstream,
                )
                for upstream in c.get("upstream_targets", c["upstreams"])
            )
            and bool(ports)
        ]
        service["project"] = project_units.get(service["unit"])
        service["imported"] = next(
            (a["name"] for a in imports if a.get("unit") == service["unit"]), None
        )
    for process in result["processes"]:
        process["listeners"] = [
            listener["address"]
            for listener in result["listeners"]
            if process["pid"] in listener["pids"]
        ]
        if not process.get("unit"):
            process["unit"] = next(
                (unit for unit, s in by_unit.items() if s["pid"] == process["pid"]), None
            )
        ports = {a.rsplit(":", 1)[-1] for a in process["listeners"] if not a.startswith("unix:")}
        process["configs"] = [
            c
            for c in configs
            if any(
                target in process["listeners"]
                or bool(ports)
                and re.search(
                    r"(?:127\.0\.0\.1|localhost|\[::1\]):(" + "|".join(ports) + r")(?:/|$)", target
                )
                for target in c.get("upstream_targets", c["upstreams"])
            )
        ]
    result["imports"] = imports
    result["static_sites"] = [c for c in configs if c["roots"] and not c["upstreams"]]
    return result


def control_service(unit: str, action: str, settings: Settings | None = None) -> dict:
    return _call(
        "host-service-action", {"unit": unit, "action": action}, settings or get_settings()
    )


@site_mutation
def adopt_site(config_id: str, name: str, unit: str = "", settings: Settings | None = None) -> dict:
    current = settings or get_settings()
    name = validate_project_name(name)
    config = nginx_config(config_id, current)
    if not config.get("site") or config.get("project"):
        raise HostError("Choose an unmanaged website config to import")
    rows = imported_apps(current)
    if any(r["name"] == name or r["config_id"] == config["id"] for r in rows):
        raise HostError("This name or config has already been imported")
    if any(p.name == name for p in list_projects(current)):
        raise HostError("A deployment project already uses that name")
    if unit:
        services = services_inventory(current)["services"]
        service = next((s for s in services if s["unit"] == unit), None)
        if service is None or service["protected"]:
            raise HostError("Select an existing application service")
    record = {
        "name": name,
        "config_id": config["id"],
        "unit": unit,
        "domains": config["domains"],
        "roots": config["roots"],
        "deleted": False,
    }
    _save_imports([*rows, record], current)
    return {
        "message": f"Imported {name} in place. Files and running processes were preserved.",
        "application": record,
    }
