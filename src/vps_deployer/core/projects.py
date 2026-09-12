from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.validation import (
    APPS_ROOT,
    PORT_RANGE,
    validate_app_path,
    validate_branch,
    validate_domain,
    validate_port,
    validate_project_name,
    validate_repository,
    validate_runtime,
    validate_service_name,
)
from vps_deployer.db.models import (
    Deployment,
    DeploymentLog,
    Domain,
    EnvironmentVariable,
    Project,
)
from vps_deployer.db.session import get_engine, init_db


class ProjectNotFoundError(LookupError):
    """Raised when a project does not exist on this VPS."""


class ProjectConflictError(ValueError):
    """Raised when a project name or port is already reserved."""


@dataclass(frozen=True)
class ProjectCreate:
    name: str
    repository: str
    branch: str = "main"
    runtime: str = "nextjs"
    port: int | None = None
    domain: str | None = None


def project_payload(project: Project) -> dict[str, object]:
    return {
        "name": project.name,
        "repository": project.repository,
        "branch": project.branch,
        "runtime": project.runtime,
        "deployment_path": project.deployment_path,
        "port": project.port,
        "domain": project.domain,
        "service_name": project.service_name,
        "enabled": project.enabled,
    }


def _session(settings: Settings | None = None) -> Session:
    current = settings or get_settings()
    init_db(current)
    return Session(get_engine(current))


def get_project(name: str, settings: Settings | None = None) -> Project:
    validated = validate_project_name(name)
    with _session(settings) as session:
        project = session.exec(select(Project).where(Project.name == validated)).first()
        if project is None:
            raise ProjectNotFoundError(f"Project not found: {validated}")
        session.expunge(project)
        return project


def list_projects(settings: Settings | None = None) -> list[Project]:
    with _session(settings) as session:
        rows = list(session.exec(select(Project).order_by(Project.name)).all())
        for row in rows:
            session.expunge(row)
        return rows


def reserved_ports(settings: Settings | None = None) -> set[int]:
    return {project.port for project in list_projects(settings)}


def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def allocate_port(requested: int | None = None, settings: Settings | None = None) -> int:
    used = reserved_ports(settings)
    if requested is not None:
        port = validate_port(requested)
        if port in used:
            raise ProjectConflictError(f"Port {port} is already reserved by another project")
        if not is_port_available(port):
            raise ProjectConflictError(f"Port {port} is already in use on 127.0.0.1")
        return port
    for port in PORT_RANGE:
        if port in used:
            continue
        if is_port_available(port):
            return port
    raise ProjectConflictError("No free application port in 33000-33999")


def create_project(data: ProjectCreate, settings: Settings | None = None) -> Project:
    name = validate_project_name(data.name)
    repository = validate_repository(data.repository)
    branch = validate_branch(data.branch)
    runtime = validate_runtime(data.runtime)
    domain = validate_domain(data.domain) if data.domain else None
    service_name = validate_service_name(name)
    deployment_path = str(validate_app_path(APPS_ROOT / name, name))
    port = allocate_port(data.port, settings)

    with _session(settings) as session:
        existing = session.exec(select(Project).where(Project.name == name)).first()
        if existing is not None:
            raise ProjectConflictError(f"Project already exists: {name}")
        project = Project(
            name=name,
            repository=repository,
            branch=branch,
            runtime=runtime,
            deployment_path=deployment_path,
            port=port,
            domain=domain,
            service_name=service_name,
            enabled=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        session.expunge(project)
        return project


def delete_project(name: str, settings: Settings | None = None) -> None:
    validated = validate_project_name(name)
    with _session(settings) as session:
        project = session.exec(select(Project).where(Project.name == validated)).first()
        if project is None:
            raise ProjectNotFoundError(f"Project not found: {validated}")
        assert project.id is not None
        deployments = session.exec(
            select(Deployment).where(Deployment.project_id == project.id)
        ).all()
        deployment_ids = {row.id for row in deployments if row.id is not None}
        logs = session.exec(select(DeploymentLog)).all()
        for log in logs:
            if log.deployment_id in deployment_ids:
                session.delete(log)
        for row in deployments:
            session.delete(row)
        for row in session.exec(select(Domain).where(Domain.project_id == project.id)).all():
            session.delete(row)
        for row in session.exec(
            select(EnvironmentVariable).where(EnvironmentVariable.project_id == project.id)
        ).all():
            session.delete(row)
        session.delete(project)
        session.commit()
