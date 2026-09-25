from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from vps_deployer.core.handover import queue_handover
from vps_deployer.core.host import (
    adopt_site,
    control_service,
    nginx_action,
    nginx_config,
    nginx_inventory,
    services_inventory,
)
from vps_deployer.core.host_admin import HostError
from vps_deployer.core.nginx import NginxError
from vps_deployer.core.projects import ProjectNotFoundError, list_projects
from vps_deployer.core.validation import ValidationError
from vps_deployer.dashboard.routes import _page, _redirect
from vps_deployer.dashboard.views import shell_context

router = APIRouter()
ERRORS = (HostError, NginxError, ValidationError, OSError, ProjectNotFoundError)


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin host administration is not allowed")


def config_url(config: str) -> str:
    return "/nginx/config?config=" + quote(config, safe="")


@router.get("/nginx", include_in_schema=False)
def nginx_page(request: Request, notice: str = "", error: str = ""):
    return _page(
        request,
        "nginx.html",
        {
            **shell_context(error=error),
            "notice": notice,
            "title": "Nginx",
            "page": "nginx",
            "inventory": nginx_inventory(),
        },
    )


@router.get("/nginx/config", include_in_schema=False)
def nginx_editor(request: Request, config: str, notice: str = "", error: str = ""):
    try:
        item = nginx_config(config)
        inventory = services_inventory()
    except ERRORS as exc:
        return _redirect("/nginx", error=str(exc))
    return _page(
        request,
        "nginx_config.html",
        {
            **shell_context(error=error),
            "notice": notice,
            "title": config,
            "page": "nginx",
            "config": item,
            "services": inventory["services"],
            "projects": list_projects(),
        },
    )


@router.post("/nginx/action", include_in_schema=False)
def nginx_form(
    request: Request,
    action: Annotated[str, Form()],
    config: Annotated[str, Form()] = "",
    revision: Annotated[str, Form()] = "",
    content: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
):
    same_origin(request)
    if action in {"disable", "delete"} and confirm != config:
        return _redirect("/nginx", error="Type the config filename/path to confirm the action")
    try:
        result = nginx_action(
            {"action": action, "id": config, "revision": revision, "content": content}
        )
    except ERRORS as exc:
        if action.startswith("save"):
            try:
                item = nginx_config(config)
                item["content"] = content
                item["revision"] = revision
                return _page(
                    request,
                    "nginx_config.html",
                    {
                        **shell_context(error=str(exc)),
                        "title": config,
                        "page": "nginx",
                        "config": item,
                        "services": services_inventory()["services"],
                        "projects": list_projects(),
                    },
                    status_code=422,
                )
            except ERRORS:
                pass
        return _redirect("/nginx", error=str(exc))
    message = str(result.get("message", "Done"))
    if result.get("backup"):
        message += ". Backup: " + result["backup"]
    if action == "test":
        message += ": " + str(result.get("test", {}).get("detail", ""))
    if config and action != "delete":
        return RedirectResponse(
            config_url(result.get("id", config)) + "&notice=" + quote(message), 303
        )
    return _redirect("/nginx", notice=message)


@router.post("/nginx/adopt", include_in_schema=False)
def adopt_form(
    request: Request,
    config: Annotated[str, Form()],
    name: Annotated[str, Form()],
    unit: Annotated[str, Form()] = "",
):
    same_origin(request)
    try:
        result = adopt_site(config, name, unit)
    except ERRORS as exc:
        return _redirect("/nginx", error=str(exc))
    return _redirect("/services", notice=result["message"])


@router.get("/services", include_in_schema=False)
def services_page(request: Request, notice: str = "", error: str = ""):
    return _page(
        request,
        "services.html",
        {
            **shell_context(error=error),
            "notice": notice,
            "title": "Services & processes",
            "page": "services",
            "inventory": services_inventory(),
        },
    )


@router.post("/services/action", include_in_schema=False)
def services_form(
    request: Request,
    unit: Annotated[str, Form()],
    action: Annotated[str, Form()],
    confirm: Annotated[str, Form()] = "",
):
    same_origin(request)
    if action in {"stop", "restart"} and confirm != unit:
        return _redirect("/services", error="Type the service name to confirm the action")
    try:
        result = control_service(unit, action)
    except ERRORS as exc:
        return _redirect("/services", error=str(exc))
    return _redirect("/services", notice=result["message"])


class HostActionBody(BaseModel):
    action: str
    id: str = ""
    revision: str = ""
    content: str = Field(default="", max_length=256000)
    confirm: str = ""


class AdoptBody(BaseModel):
    config: str
    name: str
    unit: str = ""


class ServiceBody(BaseModel):
    unit: str
    action: str
    confirm: str = ""


class HandoverBody(BaseModel):
    config: str
    project: str
    revision: str
    units: list[str] = Field(default_factory=list, max_length=10)
    confirm: str


@router.post("/api/host/handover")
def api_handover(request: Request, body: HandoverBody):
    same_origin(request)
    if body.confirm != body.config:
        raise HTTPException(422, "confirm must match the source config id")
    try:
        return queue_handover(body.config, body.project, body.units, body.revision)
    except ERRORS as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/nginx/handover", include_in_schema=False)
def handover_form(
    request: Request,
    config: Annotated[str, Form()],
    project: Annotated[str, Form()],
    revision: Annotated[str, Form()],
    confirm: Annotated[str, Form()],
    units: Annotated[str, Form()] = "",
):
    same_origin(request)
    if confirm != config:
        return _redirect(
            "/nginx",
            error="Type the source config id to confirm deployment, "
            "traffic switch and stopping the old services",
        )
    try:
        result = queue_handover(
            config, project, [u.strip() for u in units.split(",") if u.strip()], revision
        )
    except ERRORS as exc:
        return _redirect("/nginx", error=str(exc))
    return _redirect(
        "/services", notice=result["message"] + " Follow deployment logs in Projects → " + project
    )


@router.get("/api/host/nginx")
def api_nginx_inventory():
    return nginx_inventory()


@router.get("/api/host/nginx/config")
def api_nginx_read(config: str):
    try:
        return nginx_config(config)
    except ERRORS as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/host/nginx/action")
def api_nginx_action(request: Request, body: HostActionBody):
    same_origin(request)
    if body.action in {"disable", "delete"} and body.confirm != body.id:
        raise HTTPException(422, "confirm must match the config id")
    try:
        return nginx_action(body.model_dump())
    except ERRORS as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/host/import")
def api_adopt(request: Request, body: AdoptBody):
    same_origin(request)
    try:
        return adopt_site(body.config, body.name, body.unit)
    except ERRORS as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/host/services")
def api_services():
    return services_inventory()


@router.post("/api/host/services/action")
def api_service_action(request: Request, body: ServiceBody):
    same_origin(request)
    if body.action in {"stop", "restart"} and body.confirm != body.unit:
        raise HTTPException(422, "confirm must match the service name")
    try:
        return control_service(body.unit, body.action)
    except ERRORS as exc:
        raise HTTPException(422, str(exc)) from exc
