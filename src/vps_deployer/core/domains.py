from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.nginx import NginxError, apply_project_nginx, remove_project_nginx
from vps_deployer.core.projects import ProjectConflictError, get_project
from vps_deployer.core.site_config import site_mutation
from vps_deployer.core.validation import validate_domain, validate_project_name
from vps_deployer.db.models import Domain, Project
from vps_deployer.db.session import get_engine, init_db


class DomainNotFoundError(LookupError):
    """Raised when a hostname is not attached to the project."""


class DomainConflictError(ProjectConflictError):
    """Raised when a hostname is already used on this VPS."""


def domain_payload(row: Domain) -> dict[str, object]:
    return {
        "hostname": row.hostname,
        "www": row.www_enabled,
        "ssl": row.ssl_enabled,
    }


def _session(settings: Settings | None = None) -> Session:
    current = settings or get_settings()
    init_db(current)
    return Session(get_engine(current))


def claimed_hostnames(
    settings: Settings | None = None, *, exclude_project_id: int | None = None
) -> set[str]:
    claimed: set[str] = set()
    with _session(settings) as session:
        rows = list(session.exec(select(Domain)).all())
        projects = list(session.exec(select(Project)).all())
    for row in rows:
        if exclude_project_id is not None and row.project_id == exclude_project_id:
            continue
        claimed.add(row.hostname)
        if row.www_enabled and not row.hostname.startswith("www."):
            claimed.add(f"www.{row.hostname}")
    for project in projects:
        if exclude_project_id is not None and project.id == exclude_project_id:
            continue
        if project.domain:
            claimed.add(project.domain)
    return claimed


def assert_hostname_available(
    hostname: str,
    settings: Settings | None = None,
    *,
    www: bool = False,
    exclude_project_id: int | None = None,
) -> str:
    name = validate_domain(hostname)
    wanted = {name}
    if www and not name.startswith("www."):
        wanted.add(f"www.{name}")
    taken = claimed_hostnames(settings, exclude_project_id=exclude_project_id)
    from vps_deployer.core.dashboard_access import public_dashboard_hosts

    taken |= public_dashboard_hosts(settings)
    overlap = wanted & taken
    if overlap:
        raise DomainConflictError(f"Domain already in use: {sorted(overlap)[0]}")
    return name


def list_domains(project_name: str, settings: Settings | None = None) -> list[Domain]:
    project = get_project(validate_project_name(project_name), settings)
    assert project.id is not None
    with _session(settings) as session:
        rows = list(session.exec(select(Domain).where(Domain.project_id == project.id)).all())
        for row in rows:
            session.expunge(row)
        rows.sort(key=lambda item: item.hostname)
        return rows


@site_mutation
def add_domain(
    project_name: str,
    hostname: str,
    *,
    www: bool = False,
    settings: Settings | None = None,
) -> Domain:
    current = settings or get_settings()
    project = get_project(validate_project_name(project_name), current)
    from vps_deployer.core.site_config import load_site_config, require_generated_site

    require_generated_site(project.name, current)
    state = load_site_config(project.name, current)
    if state.get("provider") == "external":
        from vps_deployer.core.ssl import validate_external_certificate

        names = [validate_domain(hostname)]
        if www:
            names.append(f"www.{names[0]}")
        validate_external_certificate(
            project.name,
            state["certificate"],
            state["certificate_key"],
            names,
            current,
        )
    if www and hostname.strip().lower().startswith("www."):
        raise ValueError("Do not enable www on a hostname that already starts with www.")
    name = assert_hostname_available(hostname, current, www=www, exclude_project_id=None)
    assert project.id is not None
    with _session(current) as session:
        existing = session.exec(
            select(Domain).where(Domain.project_id == project.id, Domain.hostname == name)
        ).first()
        if existing is not None:
            raise DomainConflictError(f"Domain already attached: {name}")
        row = Domain(
            project_id=project.id,
            hostname=name,
            www_enabled=www,
            ssl_enabled=state.get("provider") == "external",
        )
        session.add(row)
        stored = session.get(Project, project.id)
        if stored is not None and stored.domain is None:
            stored.domain = name
            stored.updated_at = datetime.now(UTC)
            session.add(stored)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        if stored is not None:
            session.refresh(stored)
            session.expunge(stored)
            project = stored
    _apply(project, current)
    return row


@site_mutation
def remove_domain(
    project_name: str,
    hostname: str,
    settings: Settings | None = None,
) -> None:
    current = settings or get_settings()
    project = get_project(validate_project_name(project_name), current)
    from vps_deployer.core.site_config import require_generated_site

    require_generated_site(project.name, current)
    name = validate_domain(hostname)
    assert project.id is not None
    with _session(current) as session:
        row = session.exec(
            select(Domain).where(Domain.project_id == project.id, Domain.hostname == name)
        ).first()
        if row is None:
            raise DomainNotFoundError(f"Domain not found: {name}")
        session.delete(row)
        stored = session.get(Project, project.id)
        remaining = list(session.exec(select(Domain).where(Domain.project_id == project.id)).all())
        remaining = [item for item in remaining if item.hostname != name]
        if stored is not None and stored.domain == name:
            stored.domain = remaining[0].hostname if remaining else None
            stored.updated_at = datetime.now(UTC)
            session.add(stored)
        session.commit()
        if stored is not None:
            session.refresh(stored)
            session.expunge(stored)
            project = stored
    _apply(project, current)


def attach_initial_domain(
    project: Project, hostname: str, settings: Settings | None = None
) -> Domain:
    current = settings or get_settings()
    name = assert_hostname_available(hostname, current, exclude_project_id=project.id)
    assert project.id is not None
    with _session(current) as session:
        row = Domain(project_id=project.id, hostname=name, www_enabled=False, ssl_enabled=False)
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
    try:
        _apply(project, current)
    except NginxError:
        pass
    return row


def _apply(project: Project, settings: Settings) -> dict[str, object]:
    domains = list_domains(project.name, settings)
    if not domains:
        return remove_project_nginx(project, settings)
    return apply_project_nginx(project, domains, settings)
