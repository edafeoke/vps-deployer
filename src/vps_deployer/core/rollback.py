from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.deployments import DeploymentNotFoundError, list_deployments
from vps_deployer.core.engine import (
    _activate_symlink,
    _current_release,
    _load_manifest,
    _static_health,
    append_log,
    project_has_running,
    redact,
)
from vps_deployer.core.projects import get_project
from vps_deployer.core.runtime import get_runtime, load_start_command
from vps_deployer.core.validation import validate_app_path, validate_project_name
from vps_deployer.db.models import Deployment, Project, SystemEvent
from vps_deployer.db.session import get_engine, init_db

RESTORABLE = frozenset({"SUCCESS", "ROLLED_BACK"})


class RollbackError(RuntimeError):
    """Raised when a rollback cannot be performed safely."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _session(settings: Settings) -> Session:
    init_db(settings)
    return Session(get_engine(settings))


def _project_root(project: Project, settings: Settings) -> Path:
    assert settings.apps_root is not None
    return validate_app_path(Path(project.deployment_path), project.name, root=settings.apps_root)


def _safe_release_path(project: Project, raw: str, settings: Settings) -> Path:
    root = _project_root(project, settings)
    path = Path(raw)
    if ".." in path.parts:
        raise RollbackError("Release path is invalid")
    if not path.is_absolute():
        path = root / path
    releases = root / "releases"
    base = releases.resolve() if releases.exists() else releases
    resolved = path.resolve() if path.exists() else path
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise RollbackError("Release path is outside the project releases directory") from exc
    if not path.is_dir():
        raise RollbackError("Release directory is missing")
    return path


def find_rollback_target(
    project: Project,
    settings: Settings,
    deployment_id: int | None = None,
) -> Deployment:
    current_path = _current_release(_project_root(project, settings))
    rows = [
        row
        for row in list_deployments(project.name, settings)
        if row.status in RESTORABLE and row.release_path
    ]
    if deployment_id is not None:
        match = next((row for row in rows if row.id == deployment_id), None)
        if match is None:
            raise DeploymentNotFoundError(f"Deployment not found: {deployment_id}")
        target_path = _safe_release_path(project, match.release_path or "", settings)
        if current_path is not None and target_path.resolve() == current_path:
            raise RollbackError("That release is already current")
        return match
    for row in rows:
        try:
            target_path = _safe_release_path(project, row.release_path or "", settings)
        except RollbackError:
            continue
        if current_path is None or target_path.resolve() != current_path:
            return row
    raise RollbackError("No previous successful release is available")


def _create_record(project: Project, target: Deployment, settings: Settings) -> Deployment:
    assert project.id is not None
    with _session(settings) as session:
        row = Deployment(
            project_id=project.id,
            commit_sha=target.commit_sha,
            branch=target.branch,
            status="RUNNING",
            started_at=datetime.now(UTC),
            release_path=target.release_path,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def _finish(
    deployment_id: int,
    settings: Settings,
    *,
    status: str,
    started: datetime,
    release_path: str | None,
    error: str | None = None,
) -> Deployment:
    finished = datetime.now(UTC)
    with _session(settings) as session:
        row = session.get(Deployment, deployment_id)
        if row is None:
            raise RollbackError("Rollback record is missing", status_code=500)
        row.status = status
        row.finished_at = finished
        row.duration_seconds = int((finished - started).total_seconds())
        row.release_path = release_path
        row.error_message = error
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def rollback_project(
    project_name: str,
    deployment_id: int | None = None,
    settings: Settings | None = None,
) -> Deployment:
    current = settings or get_settings()
    current.ensure_directories()
    project = get_project(validate_project_name(project_name), current)
    if project_has_running(project.id or 0, current):
        raise RollbackError("A deployment is already running for this project")
    root = _project_root(project, current)
    active = _current_release(root)
    if active is None:
        raise RollbackError("No active release. Deploy the project first.")
    target = find_rollback_target(project, current, deployment_id)
    target_path = _safe_release_path(project, target.release_path or "", current)
    started = datetime.now(UTC)
    record = _create_record(project, target, current)
    assert record.id is not None
    runtime = get_runtime(current)
    stopped = False
    try:
        append_log(record.id, f"Rolling back to {target_path.name}", current)
        start_command = load_start_command(root)
        if start_command is None:
            manifest = _load_manifest(target_path)
            fallback = manifest.get("start_command")
            if isinstance(fallback, list) and all(isinstance(item, str) for item in fallback):
                start_command = fallback
        if start_command is None:
            _static_health(target_path)
            _activate_symlink(root, target_path)
        else:
            if runtime.is_running(project):
                runtime.stop(project)
                stopped = True
            runtime.start(project, target_path, start_command)
            runtime.wait_for_port(project)
            runtime.http_health(project)
            _activate_symlink(root, target_path)
            try:
                runtime.install(project, root / "current", start_command)
            except Exception as exc:
                append_log(record.id, f"Service unit install failed: {redact(str(exc))}", current)
            runtime.http_health(project)
        try:
            from vps_deployer.core.domains import list_domains
            from vps_deployer.core.nginx import apply_project_nginx

            domains = list_domains(project.name, current)
            if domains:
                apply_project_nginx(project, domains, current)
        except Exception as exc:
            append_log(record.id, f"nginx apply skipped: {redact(str(exc))}", current)
        result = _finish(
            record.id,
            current,
            status="ROLLED_BACK",
            started=started,
            release_path=str(target_path),
        )
        append_log(record.id, "Rollback succeeded", current)
        with _session(current) as session:
            session.add(
                SystemEvent(
                    event_type="rollback",
                    message=f"Rolled back {project.name} to {target_path.name}",
                )
            )
            session.commit()
        return result
    except Exception as exc:
        if stopped:
            try:
                command = load_start_command(root)
                if command:
                    runtime.start(project, active, command)
            except Exception:
                pass
        try:
            _activate_symlink(root, active)
        except Exception:
            pass
        message = redact(str(exc))
        result = _finish(
            record.id,
            current,
            status="FAILED",
            started=started,
            release_path=str(target_path),
            error=message[:1000],
        )
        append_log(record.id, f"Rollback failed: {message}", current)
        raise RollbackError(message, status_code=500) from exc
