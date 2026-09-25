from __future__ import annotations

from typing import Any

from sqlalchemy import text

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.dashboard_access import dashboard_status
from vps_deployer.core.deployments import (
    deployment_payload,
    list_deployment_logs,
    list_deployments,
)
from vps_deployer.core.doctor import doctor_payload
from vps_deployer.core.domains import domain_payload, list_domains
from vps_deployer.core.github import (
    GitHubAuthError,
    GitHubNotConfiguredError,
    github_status,
    list_accessible_repositories,
)
from vps_deployer.core.nginx import nginx_status
from vps_deployer.core.projects import get_project, list_projects, project_payload
from vps_deployer.core.services import project_service_status
from vps_deployer.core.ssl import ssl_status
from vps_deployer.core.validation import ALLOWED_RUNTIMES
from vps_deployer.core.version import get_version
from vps_deployer.db.session import get_engine

NOTICES = {
    "nginx_saved": "Nginx config saved. Custom edits persist across deployments.",
    "nginx_reset": "Generated Nginx config restored.",
    "created": "Project created on this VPS.",
    "deployed": "Deployment queued on this VPS.",
    "rolled_back": "Rollback finished on this VPS.",
    "started": "Application start requested.",
    "stopped": "Application stop requested.",
    "restarted": "Application restart requested.",
    "domain_added": "Domain attached on this VPS.",
    "ssl_enabled": "HTTPS enable requested.",
    "access_enabled": "Public dashboard access was updated on this VPS.",
    "password_updated": "Dashboard password updated.",
    "dashboard_ssl_enabled": "Dashboard HTTPS was requested.",
    "github_configured": "GitHub App credentials were stored on this VPS.",
    "github_connected": "GitHub App connected. Repository access is ready.",
}

LOG_LIMIT = 200


def _database_healthy(settings: Settings) -> bool:
    try:
        with get_engine(settings).connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def shell_context(
    settings: Settings | None = None,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    current = settings or get_settings()
    token = (notice or "").strip()
    message = NOTICES.get(token)
    err = (error or "").strip()
    if len(err) > 240:
        err = err[:237] + "..."
    return {
        "version": get_version(),
        "api_host": current.api_host,
        "api_port": current.api_port,
        "site_url": current.site_url,
        "notice": message,
        "error": err or None,
        "runtimes": sorted(ALLOWED_RUNTIMES),
    }


def overview_context(
    settings: Settings | None = None,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    current = settings or get_settings()
    payload = shell_context(current, notice=notice, error=error)
    doctor = doctor_payload(current)
    github = github_status(current, probe=False)
    cards: list[dict[str, Any]] = []
    for project in list_projects(current):
        deployments = list_deployments(project.name, current)
        latest = deployment_payload(deployments[0]) if deployments else None
        cards.append({"project": project_payload(project), "latest": latest})
    payload.update(
        {
            "page": "overview",
            "title": "This VPS",
            "database_healthy": _database_healthy(current),
            "doctor": doctor,
            "github_configured": bool(github.get("configured")),
            "projects": cards,
        }
    )
    return payload


def projects_context(
    settings: Settings | None = None,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    current = settings or get_settings()
    payload = shell_context(current, notice=notice, error=error)
    cards: list[dict[str, Any]] = []
    for project in list_projects(current):
        deployments = list_deployments(project.name, current)
        latest = deployment_payload(deployments[0]) if deployments else None
        cards.append({"project": project_payload(project), "latest": latest})
    payload.update({"page": "projects", "title": "Projects", "projects": cards})
    return payload


def project_context(
    name: str,
    settings: Settings | None = None,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    current = settings or get_settings()
    project = get_project(name, current)
    deployments = [deployment_payload(row) for row in list_deployments(project.name, current)]
    domains = [domain_payload(row) for row in list_domains(project.name, current)]
    logs = list_deployment_logs(project.name, settings=current)[-LOG_LIMIT:]
    payload = shell_context(current, notice=notice, error=error)
    payload.update(
        {
            "page": "project",
            "title": project.name,
            "project": project_payload(project),
            "deployments": deployments,
            "domains": domains,
            "ssl": ssl_status(project.name, current),
            "nginx": nginx_status(project.name, current),
            "service": project_service_status(project.name, current),
            "logs": logs,
            "active": any(
                isinstance(row, dict) and row.get("status") in {"QUEUED", "RUNNING"}
                for row in deployments
            ),
        }
    )
    return payload


def doctor_context(
    settings: Settings | None = None,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    current = settings or get_settings()
    payload = shell_context(current, notice=notice, error=error)
    payload.update({"page": "doctor", "title": "Doctor", "doctor": doctor_payload(current)})
    return payload


def settings_context(
    settings: Settings | None = None,
    *,
    notice: str | None = None,
    error: str | None = None,
    generated_password: str | None = None,
) -> dict[str, Any]:
    current = settings or get_settings()
    payload = shell_context(current, notice=notice, error=error)
    github = github_status(current, probe=False)
    repositories: list[dict[str, str]] = []
    repos_error: str | None = None
    if github.get("configured"):
        try:
            repositories = list_accessible_repositories(current)
        except (GitHubNotConfiguredError, GitHubAuthError) as exc:
            repos_error = str(exc)
    payload.update(
        {
            "page": "settings",
            "title": "Settings",
            "dashboard": dashboard_status(current),
            "github": github,
            "repositories": repositories,
            "repos_error": repos_error,
            "generated_password": generated_password,
        }
    )
    return payload
