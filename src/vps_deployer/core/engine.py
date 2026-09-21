from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.runtime import RuntimeProvider, get_runtime
from vps_deployer.core.validation import UNSAFE_CHARS, validate_app_path, validate_project_name
from vps_deployer.db.models import Deployment, DeploymentLog, Project
from vps_deployer.db.session import get_engine, init_db

TOKEN_RE = re.compile(r"(x-access-token:)[^@\s]+", re.IGNORECASE)
SECRET_NAMES = frozenset({"token", "password", "secret", "private_key", "authorization"})


class DeployError(RuntimeError):
    """Raised when a deployment step fails."""


def redact(text: str) -> str:
    return TOKEN_RE.sub(r"\1***", text)


def _session(settings: Settings) -> Session:
    init_db(settings)
    return Session(get_engine(settings))


def append_log(deployment_id: int, message: str, settings: Settings) -> None:
    cleaned = redact(message)
    lowered = cleaned.lower()
    if any(name in lowered and ":" in cleaned for name in SECRET_NAMES):
        if any(secret in lowered for secret in ("password=", "secret=", "token=")):
            cleaned = "[redacted log line]"
    with _session(settings) as session:
        session.add(DeploymentLog(deployment_id=deployment_id, message=cleaned[:4000]))
        session.commit()
    if settings.log_dir is not None:
        path = settings.log_dir / "projects" / "deployments.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(cleaned + "\n")


def _update_deployment(deployment_id: int, settings: Settings, **changes: Any) -> Deployment:
    with _session(settings) as session:
        row = session.get(Deployment, deployment_id)
        if row is None:
            raise DeployError(f"Deployment not found: {deployment_id}")
        for key, value in changes.items():
            setattr(row, key, value)
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def _get_deployment(deployment_id: int, settings: Settings) -> Deployment:
    with _session(settings) as session:
        row = session.get(Deployment, deployment_id)
        if row is None:
            raise DeployError(f"Deployment not found: {deployment_id}")
        session.expunge(row)
        return row


def _get_project_by_id(project_id: int, settings: Settings) -> Project:
    with _session(settings) as session:
        row = session.get(Project, project_id)
        if row is None:
            raise DeployError(f"Project not found: {project_id}")
        session.expunge(row)
        return row


def project_has_running(project_id: int, settings: Settings) -> bool:
    with _session(settings) as session:
        rows = session.exec(
            select(Deployment).where(
                Deployment.project_id == project_id, Deployment.status == "RUNNING"
            )
        ).all()
        return bool(rows)


def next_queued_deployment(settings: Settings) -> Deployment | None:
    with _session(settings) as session:
        rows = list(session.exec(select(Deployment).where(Deployment.status == "QUEUED")).all())
        rows.sort(key=lambda item: item.id or 0)
        for row in rows:
            if project_has_running(row.project_id, settings):
                continue
            session.expunge(row)
            return row
        return None


def _validate_command(command: list[str]) -> list[str]:
    if not command:
        raise DeployError("Empty command")
    for part in command:
        if any(ch in part for ch in UNSAFE_CHARS):
            raise DeployError("Command contains unsafe characters")
    return command


def _load_manifest(release_path: Path) -> dict[str, Any]:
    manifest = release_path / "vps-deployer.json"
    if not manifest.is_file():
        return {}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DeployError("vps-deployer.json is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise DeployError("vps-deployer.json must be an object")
    return payload


def _package_scripts(release_path: Path) -> set[str]:
    package = release_path / "package.json"
    if not package.is_file():
        return set()
    try:
        payload = json.loads(package.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return set()
    return {str(name) for name in scripts}


def _clone_source(project: Project, settings: Settings) -> str:
    if settings.git_clone_base is not None:
        local = Path(settings.git_clone_base) / project.repository
        if local.exists():
            return str(local)
    from vps_deployer.core.github import create_installation_token, is_github_configured

    if is_github_configured(settings):
        try:
            token = create_installation_token(settings)
            return f"https://x-access-token:{token}@github.com/{project.repository}.git"
        except Exception as exc:
            raise DeployError(
                f"GitHub App authentication failed: {exc}. "
                "Reconnect GitHub in the dashboard Settings page."
            ) from exc
    return f"https://github.com/{project.repository}.git"


def _run(
    command: list[str],
    cwd: Path,
    deployment_id: int,
    settings: Settings,
    timeout: int = 1800,
) -> None:
    safe = _validate_command(command)
    append_log(deployment_id, "$ " + redact(" ".join(safe)), settings)
    result = subprocess.run(
        safe,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.stdout:
        append_log(deployment_id, redact(result.stdout[-2000:]), settings)
    if result.stderr:
        append_log(deployment_id, redact(result.stderr[-2000:]), settings)
    if result.returncode != 0:
        raise DeployError(f"Command failed ({result.returncode}): {safe[0]}")


def _fetch_release(
    project: Project,
    release_path: Path,
    commit_sha: str | None,
    branch: str,
    deployment_id: int,
    settings: Settings,
) -> str:
    source = _clone_source(project, settings)
    release_path.mkdir(parents=True, exist_ok=False)
    _run(
        ["git", "clone", "--", source, str(release_path)],
        release_path.parent,
        deployment_id,
        settings,
        120,
    )
    if commit_sha:
        _run(["git", "checkout", "--detach", commit_sha], release_path, deployment_id, settings, 60)
    else:
        _run(["git", "checkout", branch], release_path, deployment_id, settings, 60)
    resolved = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=release_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return resolved.stdout.strip()


def _install_and_build(
    project: Project, release_path: Path, deployment_id: int, settings: Settings
) -> list[str] | None:
    manifest = _load_manifest(release_path)
    scripts = _package_scripts(release_path)
    install = manifest.get("install_command")
    if isinstance(install, list) and all(isinstance(item, str) for item in install):
        _run(install, release_path, deployment_id, settings)
    elif (release_path / "package.json").is_file():
        if (release_path / "package-lock.json").is_file():
            _run(["npm", "ci"], release_path, deployment_id, settings)
        else:
            _run(["npm", "install"], release_path, deployment_id, settings)
    elif (release_path / "pyproject.toml").is_file() or (release_path / "uv.lock").is_file():
        _run(["uv", "sync", "--no-dev"], release_path, deployment_id, settings)
    elif (release_path / "requirements.txt").is_file():
        _run(
            ["python3", "-m", "pip", "install", "-r", "requirements.txt"],
            release_path,
            deployment_id,
            settings,
        )
    elif (release_path / "composer.json").is_file():
        _run(
            ["composer", "install", "--no-dev", "--optimize-autoloader"],
            release_path,
            deployment_id,
            settings,
        )

    typecheck = manifest.get("typecheck_command")
    if isinstance(typecheck, list) and all(isinstance(item, str) for item in typecheck):
        _run(typecheck, release_path, deployment_id, settings)
    elif "typecheck" in scripts:
        _run(["npm", "run", "typecheck"], release_path, deployment_id, settings)

    build = manifest.get("build_command")
    if isinstance(build, list) and all(isinstance(item, str) for item in build):
        _run(build, release_path, deployment_id, settings)
    elif "build" in scripts:
        _run(["npm", "run", "build"], release_path, deployment_id, settings)
    elif project.runtime == "laravel" and (release_path / "artisan").is_file():
        _run(["php", "artisan", "config:cache"], release_path, deployment_id, settings)

    start = manifest.get("start_command")
    if isinstance(start, list) and all(isinstance(item, str) for item in start):
        return _validate_command(start)
    if project.runtime in {"static", "vite"}:
        return None
    if project.runtime in {"nextjs", "node"}:
        return ["npm", "start"]
    if project.runtime == "fastapi":
        return [
            "uv",
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(project.port),
        ]
    if project.runtime == "flask":
        return [
            "uv",
            "run",
            "flask",
            "--app",
            "app",
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            str(project.port),
        ]
    if project.runtime in {"laravel", "php"}:
        return ["php", "artisan", "serve", "--host", "127.0.0.1", "--port", str(project.port)]
    return None


def _activate_symlink(project_root: Path, release_path: Path) -> None:
    current = project_root / "current"
    tmp = project_root / "current.tmp"
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    os.symlink(release_path.resolve(), tmp)
    tmp.replace(current)


def _current_release(project_root: Path) -> Path | None:
    current = project_root / "current"
    if current.is_symlink() or current.exists():
        return current.resolve()
    return None


def _cleanup_releases(project_root: Path, keep: int, active: Path) -> None:
    releases = project_root / "releases"
    if not releases.is_dir():
        return
    items = sorted([path for path in releases.iterdir() if path.is_dir()], reverse=True)
    keep_set = {active.resolve()}
    for path in items:
        resolved = path.resolve()
        if resolved in keep_set:
            continue
        if len(keep_set) < keep:
            keep_set.add(resolved)
            continue
        shutil.rmtree(path, ignore_errors=True)


def _static_health(release_path: Path) -> None:
    index = release_path / "index.html"
    dist = release_path / "dist" / "index.html"
    if not index.is_file() and not dist.is_file():
        raise DeployError("Static health check failed: index.html is missing")


def execute_deployment(deployment_id: int, settings: Settings | None = None) -> Deployment:
    current = settings or get_settings()
    current.ensure_directories()
    deployment = _get_deployment(deployment_id, current)
    if deployment.status in {"SUCCESS", "FAILED", "CANCELLED"}:
        return deployment
    if project_has_running(deployment.project_id, current) and deployment.status != "RUNNING":
        return deployment

    started = datetime.now(UTC)
    deployment = _update_deployment(deployment_id, current, status="RUNNING", started_at=started)
    project = _get_project_by_id(deployment.project_id, current)
    validate_project_name(project.name)
    assert current.apps_root is not None
    project_root = validate_app_path(
        Path(project.deployment_path), project.name, root=current.apps_root
    )
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "releases").mkdir(exist_ok=True)
    (project_root / "shared").mkdir(exist_ok=True)
    (project_root / "logs").mkdir(exist_ok=True)

    stamp = started.strftime("%Y%m%d-%H%M%S")
    short = (deployment.commit_sha or "unknown")[:8]
    release_path = project_root / "releases" / f"{stamp}-{deployment_id}-{short}"
    runtime: RuntimeProvider = get_runtime(current)
    previous = _current_release(project_root)
    stopped_previous = False
    start_command: list[str] | None = None
    try:
        append_log(deployment_id, f"Fetching {project.repository}", current)
        sha = _fetch_release(
            project, release_path, deployment.commit_sha, deployment.branch, deployment_id, current
        )
        _update_deployment(deployment_id, current, commit_sha=sha, release_path=str(release_path))
        append_log(deployment_id, "Installing and building", current)
        start_command = _install_and_build(project, release_path, deployment_id, current)
        if start_command is None:
            _static_health(release_path)
            _activate_symlink(project_root, release_path)
        else:
            if runtime.is_running(project):
                runtime.stop(project)
                stopped_previous = True
            runtime.start(project, release_path, start_command)
            runtime.wait_for_port(project)
            runtime.http_health(project)
            _activate_symlink(project_root, release_path)
            try:
                runtime.install(project, project_root / "current", start_command)
            except Exception as exc:
                append_log(
                    deployment_id,
                    f"Service unit install failed: {redact(str(exc))}",
                    current,
                )
            runtime.http_health(project)
        finished = datetime.now(UTC)
        deployment = _update_deployment(
            deployment_id,
            current,
            status="SUCCESS",
            finished_at=finished,
            duration_seconds=int((finished - started).total_seconds()),
            release_path=str(release_path),
            error_message=None,
        )
        append_log(deployment_id, "Deployment succeeded", current)
        try:
            from vps_deployer.core.domains import list_domains
            from vps_deployer.core.nginx import apply_project_nginx

            domains = list_domains(project.name, current)
            if domains:
                apply_project_nginx(project, domains, current)
                append_log(deployment_id, "nginx site updated", current)
        except Exception as exc:
            append_log(deployment_id, f"nginx apply skipped: {redact(str(exc))}", current)
        _cleanup_releases(project_root, current.release_retention, release_path)
        return deployment
    except Exception as exc:
        if start_command is not None:
            try:
                runtime.stop(project)
            except Exception:
                pass
        if stopped_previous and previous is not None and previous.exists():
            try:
                fallback = _load_manifest(previous).get("start_command")
                command = fallback if isinstance(fallback, list) else ["npm", "start"]
                if all(isinstance(item, str) for item in command):
                    runtime.start(project, previous, command)
            except Exception:
                pass
        finished = datetime.now(UTC)
        message = redact(str(exc))
        deployment = _update_deployment(
            deployment_id,
            current,
            status="FAILED",
            finished_at=finished,
            duration_seconds=int((finished - started).total_seconds()),
            release_path=str(release_path) if release_path.exists() else None,
            error_message=message[:1000],
        )
        append_log(deployment_id, f"Deployment failed: {message}", current)
        return deployment


class DeploymentWorker:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        self._stop = threading.Event()
        self._wakeup = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="vps-deployer-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def wakeup(self) -> None:
        self._wakeup.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = self.settings or get_settings()
            job = next_queued_deployment(settings)
            if job is None or job.id is None:
                self._wakeup.wait(timeout=2.0)
                self._wakeup.clear()
                continue
            execute_deployment(job.id, settings)


_worker: DeploymentWorker | None = None


def start_worker(settings: Settings | None = None) -> DeploymentWorker:
    global _worker
    if _worker is None:
        _worker = DeploymentWorker(settings)
        _worker.start()
    return _worker


def stop_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None


def notify_worker() -> None:
    if _worker is not None:
        _worker.wakeup()
