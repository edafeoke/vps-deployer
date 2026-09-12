from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from vps_deployer.core.config import get_settings
from vps_deployer.core.dashboard_access import (
    SESSION_COOKIE,
    requires_dashboard_auth,
    valid_session_cookie,
)
from vps_deployer.core.deployments import (
    DeploymentNotFoundError,
    deployment_payload,
    list_deployment_logs,
    list_deployments,
    queue_deployment,
)
from vps_deployer.core.doctor import doctor_payload
from vps_deployer.core.domains import (
    DomainConflictError,
    DomainNotFoundError,
    add_domain,
    domain_payload,
    list_domains,
    remove_domain,
)
from vps_deployer.core.engine import notify_worker, start_worker, stop_worker
from vps_deployer.core.github import (
    GitHubAuthError,
    GitHubNotConfiguredError,
    WebhookError,
    configure_github,
    github_status,
    handle_github_webhook,
    list_accessible_repositories,
)
from vps_deployer.core.nginx import NginxError, apply_project_nginx
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
from vps_deployer.core.rollback import RollbackError, rollback_project
from vps_deployer.core.services import (
    ServiceError,
    project_service_logs,
    project_service_status,
    restart_project,
    start_project,
    stop_project,
)
from vps_deployer.core.ssl import SslError, enable_ssl, renew_certificates, ssl_status
from vps_deployer.core.validation import ValidationError
from vps_deployer.core.version import get_version
from vps_deployer.dashboard.routes import mount_dashboard_static
from vps_deployer.dashboard.routes import router as dashboard_router
from vps_deployer.db.session import get_engine, init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    init_db(settings)
    if settings.worker_enabled:
        start_worker(settings)
    yield
    stop_worker()


app = FastAPI(
    title="VPS Deployer",
    description="Local API for this VPS Deployer installation. Bound to localhost.",
    version=get_version(),
    lifespan=lifespan,
)
app.include_router(dashboard_router)
mount_dashboard_static(app)


@app.middleware("http")
async def require_public_dashboard_login(request: Request, call_next):
    settings = get_settings()
    if not requires_dashboard_auth(request.headers.get("host"), request.url.path, settings):
        return await call_next(request)
    if valid_session_cookie(request.cookies.get(SESSION_COOKIE), settings):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    nxt = request.url.path
    if request.url.query:
        nxt = f"{nxt}?{request.url.query}"
    return RedirectResponse(f"/login?next={quote(nxt, safe='')}", status_code=303)


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
    if isinstance(exc, (ProjectNotFoundError, DeploymentNotFoundError, DomainNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ServiceError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, NginxError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, SslError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, RollbackError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
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


class DeployBody(BaseModel):
    commit: str | None = None


@app.post("/api/projects/{project}/deploy", status_code=202)
def api_deploy_project(project: str, body: DeployBody | None = None) -> dict[str, object]:
    payload = body or DeployBody()
    try:
        row = get_project(project, get_settings())
        deployment = queue_deployment(row.name, payload.commit, row.branch, get_settings())
    except (ValidationError, ProjectNotFoundError) as exc:
        raise _project_error(exc) from exc
    notify_worker()
    return {"status": "QUEUED", "deployment": deployment_payload(deployment)}


@app.get("/api/projects/{project}/logs")
def api_project_logs(project: str, deployment_id: int | None = None) -> dict[str, object]:
    try:
        lines = list_deployment_logs(project, deployment_id, get_settings())
    except (ValidationError, ProjectNotFoundError, DeploymentNotFoundError) as exc:
        raise _project_error(exc) from exc
    return {"lines": lines}


@app.get("/api/projects/{project}/deployments")
def api_list_deployments(project: str) -> dict[str, object]:
    try:
        rows = list_deployments(project, get_settings())
    except (ValidationError, ProjectNotFoundError) as exc:
        raise _project_error(exc) from exc
    return {"deployments": [deployment_payload(row) for row in rows]}


class RollbackBody(BaseModel):
    deployment_id: int | None = None


@app.post("/api/projects/{project}/rollback")
def api_rollback_project(project: str, body: RollbackBody | None = None) -> dict[str, object]:
    payload = body or RollbackBody()
    try:
        deployment = rollback_project(project, payload.deployment_id, get_settings())
    except (
        ValidationError,
        ProjectNotFoundError,
        DeploymentNotFoundError,
        RollbackError,
    ) as exc:
        raise _project_error(exc) from exc
    return {"status": deployment.status, "deployment": deployment_payload(deployment)}


@app.post("/api/projects/{project}/start")
def api_start_project(project: str) -> dict[str, object]:
    try:
        return start_project(project, get_settings())
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        raise _project_error(exc) from exc


@app.post("/api/projects/{project}/stop")
def api_stop_project(project: str) -> dict[str, object]:
    try:
        return stop_project(project, get_settings())
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        raise _project_error(exc) from exc


@app.post("/api/projects/{project}/restart")
def api_restart_project(project: str) -> dict[str, object]:
    try:
        return restart_project(project, get_settings())
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        raise _project_error(exc) from exc


@app.get("/api/projects/{project}/service")
def api_project_service(project: str) -> dict[str, object]:
    try:
        return project_service_status(project, get_settings())
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        raise _project_error(exc) from exc


@app.get("/api/projects/{project}/service/logs")
def api_project_service_logs(project: str) -> dict[str, object]:
    try:
        return {"lines": project_service_logs(project, settings=get_settings())}
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        raise _project_error(exc) from exc


class DomainAddBody(BaseModel):
    hostname: str
    www: bool = False


@app.get("/api/projects/{project}/domains")
def api_list_domains(project: str) -> dict[str, object]:
    try:
        rows = list_domains(project, get_settings())
    except (ValidationError, ProjectNotFoundError) as exc:
        raise _project_error(exc) from exc
    return {"domains": [domain_payload(row) for row in rows]}


@app.post("/api/projects/{project}/domains", status_code=201)
def api_add_domain(project: str, body: DomainAddBody) -> dict[str, object]:
    try:
        row = add_domain(project, body.hostname, www=body.www, settings=get_settings())
    except (
        ValidationError,
        ProjectNotFoundError,
        DomainConflictError,
        NginxError,
        ValueError,
    ) as exc:
        if isinstance(exc, ValueError) and not isinstance(
            exc, (ValidationError, ProjectConflictError)
        ):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise _project_error(exc) from exc
    return domain_payload(row)


@app.delete("/api/projects/{project}/domains/{hostname}")
def api_remove_domain(project: str, hostname: str) -> dict[str, str]:
    try:
        remove_domain(project, hostname, get_settings())
    except (ValidationError, ProjectNotFoundError, DomainNotFoundError, NginxError) as exc:
        raise _project_error(exc) from exc
    return {"status": "deleted", "hostname": hostname}


@app.post("/api/projects/{project}/nginx")
def api_apply_nginx(project: str) -> dict[str, object]:
    try:
        row = get_project(project, get_settings())
        domains = list_domains(row.name, get_settings())
        return apply_project_nginx(row, domains, get_settings())
    except (ValidationError, ProjectNotFoundError, NginxError) as exc:
        raise _project_error(exc) from exc


class SslEnableBody(BaseModel):
    hostname: str | None = None
    email: str | None = None


@app.get("/api/projects/{project}/ssl")
def api_ssl_status(project: str) -> dict[str, object]:
    try:
        return ssl_status(project, get_settings())
    except (ValidationError, ProjectNotFoundError) as exc:
        raise _project_error(exc) from exc


@app.post("/api/projects/{project}/ssl")
def api_enable_ssl(project: str, body: SslEnableBody | None = None) -> dict[str, object]:
    payload = body or SslEnableBody()
    try:
        return enable_ssl(project, payload.hostname, payload.email, get_settings())
    except (
        ValidationError,
        ProjectNotFoundError,
        DomainNotFoundError,
        NginxError,
        SslError,
    ) as exc:
        raise _project_error(exc) from exc


@app.post("/api/ssl/renew")
def api_renew_ssl() -> dict[str, object]:
    try:
        return renew_certificates(get_settings())
    except SslError as exc:
        raise _project_error(exc) from exc


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
