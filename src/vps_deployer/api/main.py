from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from vps_deployer.core.config import get_settings
from vps_deployer.core.deployments import deployment_payload, list_deployments
from vps_deployer.core.doctor import doctor_payload
from vps_deployer.core.github import (
    GitHubAuthError,
    GitHubNotConfiguredError,
    WebhookError,
    configure_github,
    github_status,
    handle_github_webhook,
    list_accessible_repositories,
)
from vps_deployer.core.projects import (
    ProjectConflictError,
    ProjectCreate,
    ProjectNotFoundError,
    create_project,
    delete_project,
    get_project,
    list_projects,
    project_payload,
)
from vps_deployer.core.validation import ValidationError
from vps_deployer.core.version import get_version
from vps_deployer.db.session import get_engine, init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    init_db(settings)
    yield


app = FastAPI(
    title="VPS Deployer",
    description="Local API for this VPS Deployer installation. Bound to localhost.",
    version=get_version(),
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict[str, object]:
    settings = get_settings()
    database_healthy = False
    try:
        engine = get_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_healthy = True
    except Exception:
        database_healthy = False
    return {
        "name": "VPS Deployer",
        "version": get_version(),
        "api": {
            "host": settings.api_host,
            "port": settings.api_port,
            "healthy": True,
        },
        "database": {
            "healthy": database_healthy,
            "path": str(settings.database_path),
        },
        "site_url": settings.site_url,
    }


class ProjectCreateBody(BaseModel):
    name: str
    repository: str
    branch: str = "main"
    runtime: str = "nextjs"
    port: int | None = None
    domain: str | None = Field(default=None)


def _project_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ProjectConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected project error")


@app.get("/api/projects")
def api_list_projects() -> dict[str, object]:
    rows = list_projects(get_settings())
    return {"projects": [project_payload(row) for row in rows]}


@app.post("/api/projects", status_code=201)
def api_create_project(body: ProjectCreateBody) -> dict[str, object]:
    try:
        project = create_project(
            ProjectCreate(
                name=body.name,
                repository=body.repository,
                branch=body.branch,
                runtime=body.runtime,
                port=body.port,
                domain=body.domain,
            ),
            get_settings(),
        )
    except (ValidationError, ProjectConflictError) as exc:
        raise _project_error(exc) from exc
    return project_payload(project)


@app.get("/api/projects/{project}")
def api_get_project(project: str) -> dict[str, Any]:
    try:
        row = get_project(project, get_settings())
    except (ValidationError, ProjectNotFoundError) as exc:
        raise _project_error(exc) from exc
    return project_payload(row)


@app.delete("/api/projects/{project}")
def api_delete_project(project: str) -> dict[str, str]:
    try:
        delete_project(project, get_settings())
    except (ValidationError, ProjectNotFoundError) as exc:
        raise _project_error(exc) from exc
    return {"status": "deleted", "name": project}


@app.get("/api/projects/{project}/deployments")
def api_list_deployments(project: str) -> dict[str, object]:
    try:
        rows = list_deployments(project, get_settings())
    except (ValidationError, ProjectNotFoundError) as exc:
        raise _project_error(exc) from exc
    return {"deployments": [deployment_payload(row) for row in rows]}


class GitHubConfigureBody(BaseModel):
    app_id: str
    private_key: str
    webhook_secret: str
    installation_id: str | None = None


@app.get("/api/github/status")
def api_github_status() -> dict[str, object]:
    return github_status(get_settings(), probe=False)


@app.post("/api/github/configure")
def api_github_configure(body: GitHubConfigureBody) -> dict[str, object]:
    try:
        configure_github(
            app_id=body.app_id,
            private_key=body.private_key,
            webhook_secret=body.webhook_secret,
            installation_id=body.installation_id,
            settings=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return github_status(get_settings(), probe=False)


@app.get("/api/github/repos")
def api_github_repos() -> dict[str, object]:
    try:
        repositories = list_accessible_repositories(get_settings())
    except GitHubNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GitHubAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"repositories": repositories}


@app.post("/api/github/webhook")
async def api_github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, object]:
    body = await request.body()
    try:
        return handle_github_webhook(body, x_hub_signature_256, x_github_event, get_settings())
    except GitHubNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WebhookError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/system/doctor")
def system_doctor() -> dict[str, object]:
    return doctor_payload(get_settings())
