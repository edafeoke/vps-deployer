from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.projects import ProjectNotFoundError, get_project, list_projects
from vps_deployer.core.validation import validate_branch, validate_repository
from vps_deployer.db.models import Deployment, DeploymentLog, Project
from vps_deployer.db.session import get_engine, init_db

ACTIVE_STATUSES = frozenset({"QUEUED", "RUNNING"})


class DeploymentNotFoundError(LookupError):
    """Raised when a deployment does not exist."""


def deployment_payload(row: Deployment) -> dict[str, object]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "commit_sha": row.commit_sha,
        "branch": row.branch,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "duration_seconds": row.duration_seconds,
        "release_path": row.release_path,
        "error_message": row.error_message,
    }


def find_projects_for_repository(
    repository: str, settings: Settings | None = None
) -> list[Project]:
    wanted = validate_repository(repository).casefold()
    matches = [row for row in list_projects(settings) if row.repository.casefold() == wanted]
    return matches


def queue_deployment(
    project_name: str,
    commit_sha: str | None,
    branch: str,
    settings: Settings | None = None,
) -> Deployment:
    project = get_project(project_name, settings)
    validated_branch = validate_branch(branch)
    if project.branch != validated_branch:
        raise ProjectNotFoundError(
            f"Project {project.name} tracks branch {project.branch}, not {validated_branch}"
        )
    current = settings or get_settings()
    init_db(current)
    assert project.id is not None
    with Session(get_engine(current)) as session:
        row = Deployment(
            project_id=project.id,
            commit_sha=commit_sha,
            branch=validated_branch,
            status="QUEUED",
            started_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def list_deployments(project_name: str, settings: Settings | None = None) -> list[Deployment]:
    project = get_project(project_name, settings)
    current = settings or get_settings()
    init_db(current)
    assert project.id is not None
    project_id = project.id
    with Session(get_engine(current)) as session:
        query = select(Deployment).where(Deployment.project_id == project_id)
        rows = list(session.exec(query).all())
        for row in rows:
            session.expunge(row)
        rows.sort(key=lambda item: item.id or 0, reverse=True)
        return rows


def list_deployment_logs(
    project_name: str,
    deployment_id: int | None = None,
    settings: Settings | None = None,
) -> list[str]:
    rows = list_deployments(project_name, settings)
    if not rows:
        return []
    chosen = rows[0]
    if deployment_id is not None:
        match = next((row for row in rows if row.id == deployment_id), None)
        if match is None:
            raise DeploymentNotFoundError(f"Deployment not found: {deployment_id}")
        chosen = match
    assert chosen.id is not None
    current = settings or get_settings()
    init_db(current)
    with Session(get_engine(current)) as session:
        query = select(DeploymentLog).where(DeploymentLog.deployment_id == chosen.id)
        logs = list(session.exec(query).all())
        logs.sort(key=lambda item: item.id or 0)
        return [row.message for row in logs]


def queue_push_event(
    repository: str,
    branch: str,
    commit_sha: str,
    settings: Settings | None = None,
) -> list[Deployment]:
    matches = find_projects_for_repository(repository, settings)
    if not matches:
        raise ProjectNotFoundError(f"Unknown repository: {repository}")
    branch_matches = [row for row in matches if row.branch == branch]
    if not branch_matches:
        raise ValueError(f"Unsupported branch: {branch}")
    queued: list[Deployment] = []
    for project in branch_matches:
        queued.append(queue_deployment(project.name, commit_sha, branch, settings))
    return queued
