"""Deploy a replacement first, then transfer the existing site and stop old services."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.deployments import deployment_payload, list_deployments, queue_deployment
from vps_deployer.core.host import (
    _call,
    _save_imports,
    imported_apps,
    nginx_config,
    services_inventory,
)
from vps_deployer.core.host_admin import HostError, handover_content
from vps_deployer.core.projects import get_project
from vps_deployer.core.site_config import load_site_config, save_site_config, site_mutation
from vps_deployer.core.validation import validate_domain
from vps_deployer.db.models import Domain, Project
from vps_deployer.db.session import get_engine


def _validate(config_id: str, project_name: str, units: list[str], settings: Settings):
    project = get_project(project_name, settings)
    config = nginx_config(config_id, settings)
    if config.get("project") or not config.get("site") or not config.get("enabled"):
        raise HostError("Select an enabled unmanaged/imported website")
    if load_site_config(project.name, settings).get("host_config_id"):
        raise HostError("The target project already owns a transferred website")
    names = list(dict.fromkeys(validate_domain(h) for h in config["domains"]))
    if not names:
        raise HostError("The source website has no transferable domains")
    with Session(get_engine(settings)) as session:
        domains = session.exec(select(Domain)).all()
        if any(d.project_id == project.id for d in domains) or project.domain:
            raise HostError(
                "Create the replacement project without a domain; "
                "handover transfers the existing domains"
            )
        if any(
            d.hostname in names or d.www_enabled and "www." + d.hostname in names for d in domains
        ):
            raise HostError("A source hostname already belongs to another deployment project")
    assert settings.apps_root is not None
    handover_content(
        config["content"], project.name, project.port, project.runtime, settings.apps_root
    )
    services = services_inventory(settings)["services"]
    for unit in units:
        service = next((s for s in services if s["unit"] == unit), None)
        if (
            not service
            or service["protected"]
            or service.get("project")
            or not any(c["id"] == config["id"] for c in service["configs"])
        ):
            raise HostError(
                "Old services must be unprotected applications linked to this Nginx config"
            )
        if any(c["id"] != config["id"] and c["enabled"] for c in service["configs"]):
            raise HostError(
                "An old service also serves other enabled websites; migrate those separately first"
            )
    if config["upstreams"] and not units:
        raise HostError(
            "Select the old systemd service(s) to stop. "
            "Unsupervised processes require manual migration."
        )
    return project, config, names


@site_mutation
def queue_handover(
    config_id: str,
    project_name: str,
    units: list[str],
    expected_revision: str,
    settings: Settings | None = None,
) -> dict:
    current = settings or get_settings()
    units = list(dict.fromkeys(units))
    project, config, _ = _validate(config_id, project_name, units, current)
    if config["revision"] != expected_revision:
        raise HostError("Source config changed. Reload before requesting handover.")
    if any(d.status in {"QUEUED", "RUNNING"} for d in list_deployments(project.name, current)):
        raise HostError("Wait for the target project’s active deployment to finish")
    # The worker takes the same site lock before cutover, so it cannot consume half-written intent.
    deployment = queue_deployment(project.name, None, project.branch, current)
    state = load_site_config(project.name, current)
    state["pending_handover"] = json.dumps(
        {
            "deployment_id": deployment.id,
            "id": config["id"],
            "revision": expected_revision,
            "units": units,
        }
    )
    try:
        save_site_config(project.name, state, current)
    except Exception:
        with Session(get_engine(current)) as session:
            from vps_deployer.db.models import Deployment

            row = session.get(Deployment, deployment.id)
            if row is not None:
                row.status = "CANCELLED"
                session.add(row)
                session.commit()
        raise
    return {
        "message": "Deployment and handover queued. The old website stays online "
        "until the new app passes health checks.",
        "deployment": deployment_payload(deployment),
    }


@site_mutation
def complete_handover(project: Project, deployment_id: int, settings: Settings) -> bool:
    assert project.id is not None
    before = load_site_config(project.name, settings)
    intent = json.loads(before.get("pending_handover", "{}"))
    if intent.get("deployment_id") != deployment_id:
        return False
    if project.runtime in {"static", "vite"}:
        root = Path(project.deployment_path) / "current"
        if project.runtime == "vite":
            root /= "dist"
        if not (root / "index.html").is_file():
            raise HostError(
                "Replacement document root has no index.html; old website was not touched"
            )
    _, config, names = _validate(intent["id"], project.name, intent["units"], settings)
    if config["revision"] != intent["revision"]:
        raise HostError("Source config changed during deployment; old website was not touched")
    imports = imported_apps(settings)
    result = _call(
        "host-handover",
        {**intent, "project": project.name, "port": project.port, "runtime": project.runtime},
        settings,
    )
    try:
        state = {k: v for k, v in before.items() if k != "pending_handover"}
        state.update(host_config_id=config["id"], handover_backup=result["backup"])
        if result.get("certificate"):
            state.update(
                provider="external",
                certificate=result["certificate"],
                certificate_key=result["certificate_key"],
            )
        with Session(get_engine(settings)) as session:
            for name in names:
                session.add(
                    Domain(
                        project_id=project.id,
                        hostname=name,
                        ssl_enabled=bool(result.get("certificate")),
                    )
                )
            row = session.get(Project, project.id)
            assert row is not None
            row.domain = names[0]
            session.add(row)
            save_site_config(project.name, state, settings)
            _save_imports([a for a in imports if a["config_id"] != config["id"]], settings)
            session.commit()
    except Exception as exc:
        recovery_errors = []
        for restore in (
            lambda: _call("host-handover-rollback", {"backup": result["backup"]}, settings),
            lambda: save_site_config(project.name, before, settings),
            lambda: _save_imports(imports, settings),
        ):
            try:
                restore()
            except Exception as recovery_error:
                recovery_errors.append(str(recovery_error))
        if recovery_errors:
            raise HostError(
                f"{exc}; incomplete recovery: {recovery_errors}. Backup: {result['backup']}"
            ) from exc
        raise
    return True


@site_mutation
def fail_handover(project: Project, deployment_id: int, settings: Settings) -> None:
    state = load_site_config(project.name, settings)
    intent = json.loads(state.get("pending_handover", "{}"))
    if intent.get("deployment_id") == deployment_id:
        state.pop("pending_handover", None)
        save_site_config(project.name, state, settings)
