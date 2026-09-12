from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from vps_deployer.core.config import get_settings
from vps_deployer.core.dashboard_access import (
    SESSION_COOKIE,
    DashboardAccessError,
    authenticate_dashboard,
    safe_next_path,
    session_cookie_kwargs,
    valid_session_cookie,
)
from vps_deployer.core.deployments import queue_deployment
from vps_deployer.core.domains import DomainNotFoundError, add_domain
from vps_deployer.core.engine import notify_worker
from vps_deployer.core.nginx import NginxError
from vps_deployer.core.projects import (
    ProjectConflictError,
    ProjectCreate,
    ProjectNotFoundError,
    create_project,
    get_project,
)
from vps_deployer.core.rollback import RollbackError, rollback_project
from vps_deployer.core.services import ServiceError, restart_project, start_project, stop_project
from vps_deployer.core.ssl import SslError, enable_ssl
from vps_deployer.core.validation import ValidationError
from vps_deployer.dashboard import STATIC_DIR, TEMPLATE_DIR
from vps_deployer.dashboard.views import (
    doctor_context,
    overview_context,
    project_context,
    projects_context,
    shell_context,
)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def mount_dashboard_static(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _page(
    request: Request,
    name: str,
    context: dict[str, object],
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def _redirect(
    path: str, *, notice: str | None = None, error: str | None = None
) -> RedirectResponse:
    query: list[str] = []
    if notice:
        query.append(f"notice={quote(notice, safe='')}")
    if error:
        query.append(f"error={quote(error, safe='')}")
    if query:
        path = f"{path}?{'&'.join(query)}"
    return RedirectResponse(path, status_code=303)


def _form_error(exc: Exception) -> str:
    return str(exc)


@router.get("/login", response_class=HTMLResponse)
def dashboard_login_form(
    request: Request,
    next: str | None = None,
    error: str | None = None,
):
    destination = safe_next_path(next)
    if valid_session_cookie(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(destination, status_code=303)
    context = {
        **shell_context(error=error),
        "page": "login",
        "title": "Sign in",
        "next": destination,
    }
    return _page(request, "login.html", context)


@router.post("/login")
def dashboard_login(
    request: Request,
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    destination = safe_next_path(next)
    try:
        token = authenticate_dashboard(password, get_settings())
    except DashboardAccessError as exc:
        context = {
            **shell_context(error=str(exc)),
            "page": "login",
            "title": "Sign in",
            "next": destination,
        }
        return _page(request, "login.html", context, status_code=401)
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(SESSION_COOKIE, token, **session_cookie_kwargs())
    return response


@router.post("/logout")
def dashboard_logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/", response_class=HTMLResponse)
def dashboard_overview(request: Request, notice: str | None = None, error: str | None = None):
    return _page(request, "overview.html", overview_context(notice=notice, error=error))


@router.get("/projects", response_class=HTMLResponse)
def dashboard_projects(request: Request, notice: str | None = None, error: str | None = None):
    return _page(request, "projects.html", projects_context(notice=notice, error=error))


@router.post("/projects")
def dashboard_create_project(
    name: Annotated[str, Form()],
    repository: Annotated[str, Form()],
    branch: Annotated[str, Form()] = "main",
    runtime: Annotated[str, Form()] = "nextjs",
    port: Annotated[str, Form()] = "",
    domain: Annotated[str, Form()] = "",
) -> RedirectResponse:
    settings = get_settings()
    port_value: int | None = None
    if port.strip():
        try:
            port_value = int(port.strip())
        except ValueError:
            return _redirect("/projects", error="Port must be an integer in 33000-33999")
    try:
        project = create_project(
            ProjectCreate(
                name=name.strip(),
                repository=repository.strip(),
                branch=branch.strip() or "main",
                runtime=runtime.strip() or "nextjs",
                port=port_value,
                domain=domain.strip() or None,
            ),
            settings,
        )
    except (ValidationError, ProjectConflictError) as exc:
        return _redirect("/projects", error=_form_error(exc))
    return _redirect(f"/projects/{project.name}", notice="created")


@router.get("/projects/{name}", response_class=HTMLResponse)
def dashboard_project(
    request: Request,
    name: str,
    notice: str | None = None,
    error: str | None = None,
):
    try:
        context = project_context(name, notice=notice, error=error)
    except ValidationError as exc:
        return _page(
            request,
            "missing.html",
            {**shell_context(error=str(exc)), "page": "projects", "title": "Invalid project"},
            status_code=422,
        )
    except ProjectNotFoundError:
        return _page(
            request,
            "missing.html",
            {**shell_context(), "page": "projects", "title": "Project not found", "name": name},
            status_code=404,
        )
    return _page(request, "project.html", context)


@router.post("/projects/{name}/deploy")
def dashboard_deploy(name: str) -> RedirectResponse:
    settings = get_settings()
    try:
        project = get_project(name, settings)
        queue_deployment(project.name, None, project.branch, settings)
    except (ValidationError, ProjectNotFoundError) as exc:
        return _redirect("/projects", error=_form_error(exc))
    notify_worker()
    return _redirect(f"/projects/{name}", notice="deployed")


@router.post("/projects/{name}/rollback")
def dashboard_rollback(name: str) -> RedirectResponse:
    try:
        rollback_project(name, None, get_settings())
    except (ValidationError, ProjectNotFoundError, RollbackError) as exc:
        return _redirect(f"/projects/{name}", error=_form_error(exc))
    return _redirect(f"/projects/{name}", notice="rolled_back")


@router.post("/projects/{name}/start")
def dashboard_start(name: str) -> RedirectResponse:
    try:
        start_project(name, get_settings())
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        return _redirect(f"/projects/{name}", error=_form_error(exc))
    return _redirect(f"/projects/{name}", notice="started")


@router.post("/projects/{name}/stop")
def dashboard_stop(name: str) -> RedirectResponse:
    try:
        stop_project(name, get_settings())
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        return _redirect(f"/projects/{name}", error=_form_error(exc))
    return _redirect(f"/projects/{name}", notice="stopped")


@router.post("/projects/{name}/restart")
def dashboard_restart(name: str) -> RedirectResponse:
    try:
        restart_project(name, get_settings())
    except (ValidationError, ProjectNotFoundError, ServiceError) as exc:
        return _redirect(f"/projects/{name}", error=_form_error(exc))
    return _redirect(f"/projects/{name}", notice="restarted")


@router.post("/projects/{name}/domains")
def dashboard_add_domain(
    name: str,
    hostname: Annotated[str, Form()],
    www: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    try:
        add_domain(name, hostname.strip(), www=www is not None, settings=get_settings())
    except (
        ValidationError,
        ProjectNotFoundError,
        ProjectConflictError,
        NginxError,
        ValueError,
    ) as exc:
        return _redirect(f"/projects/{name}", error=_form_error(exc))
    return _redirect(f"/projects/{name}", notice="domain_added")


@router.post("/projects/{name}/ssl")
def dashboard_enable_ssl(
    name: str,
    email: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        enable_ssl(name, None, email.strip() or None, get_settings())
    except (
        ValidationError,
        ProjectNotFoundError,
        DomainNotFoundError,
        NginxError,
        SslError,
    ) as exc:
        return _redirect(f"/projects/{name}", error=_form_error(exc))
    return _redirect(f"/projects/{name}", notice="ssl_enabled")


@router.get("/doctor", response_class=HTMLResponse)
def dashboard_doctor(request: Request, notice: str | None = None, error: str | None = None):
    return _page(request, "doctor.html", doctor_context(notice=notice, error=error))
