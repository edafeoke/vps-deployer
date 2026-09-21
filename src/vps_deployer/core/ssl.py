from __future__ import annotations

import json
import os
import pwd
import subprocess
from pathlib import Path

from sqlmodel import Session, select

from vps_deployer.core.config import PRODUCTION_CONFIG_DIR, Settings, get_settings
from vps_deployer.core.domains import DomainNotFoundError, list_domains
from vps_deployer.core.helper import HelperError, helper_available, require_helper
from vps_deployer.core.nginx import apply_project_nginx, certificate_directory, project_hostnames
from vps_deployer.core.projects import get_project
from vps_deployer.core.validation import validate_domain, validate_email, validate_project_name
from vps_deployer.db.models import Domain
from vps_deployer.db.session import get_engine, init_db

SERVICE_USER = "vps-deployer"


class SslError(RuntimeError):
    """Raised when a certificate cannot be issued or renewed."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def ssl_email_path(settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    assert current.config_dir is not None
    return current.config_dir / "ssl.json"


def load_ssl_email(settings: Settings | None = None) -> str | None:
    current = settings or get_settings()
    if current.ssl_email:
        return current.ssl_email
    path = ssl_email_path(current)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    email = payload.get("email") if isinstance(payload, dict) else None
    return str(email) if isinstance(email, str) and email else None


def save_ssl_email(email: str, settings: Settings | None = None) -> str:
    current = settings or get_settings()
    current.ensure_directories()
    validated = validate_email(email)
    path = ssl_email_path(current)
    identity: tuple[int, int] | None = None
    if current.config_dir == PRODUCTION_CONFIG_DIR:
        try:
            account = pwd.getpwnam(SERVICE_USER)
        except KeyError as exc:
            raise SslError(f"Service user {SERVICE_USER} does not exist") from exc
        identity = (account.pw_uid, account.pw_gid)
        if os.geteuid() not in {0, identity[0]}:
            raise SslError("Run SSL configuration with sudo on a production install")
    path.write_text(json.dumps({"email": validated}) + "\n", encoding="utf-8")
    path.chmod(0o600)
    if identity is not None and os.geteuid() == 0:
        os.chown(path, *identity)
    return validated


def _issue_local_certificate(hostname: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-days",
            "1",
            "-keyout",
            str(dest / "privkey.pem"),
            "-out",
            str(dest / "fullchain.pem"),
            "-subj",
            f"/CN={hostname}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SslError("Unable to create a local certificate")
    (dest / "privkey.pem").chmod(0o600)


def _issue_letsencrypt(
    email: str, cert_name: str, hostnames: list[str], settings: Settings
) -> None:
    if not helper_available(settings):
        raise SslError("Privileged helper is not installed", status_code=409)
    try:
        require_helper("ssl-issue", email, cert_name, *hostnames, settings=settings)
    except HelperError as exc:
        raise SslError(str(exc)) from exc


def _mark_ssl(project_id: int, enabled: bool, settings: Settings) -> None:
    init_db(settings)
    with Session(get_engine(settings)) as session:
        rows = list(session.exec(select(Domain).where(Domain.project_id == project_id)).all())
        for row in rows:
            row.ssl_enabled = enabled
            session.add(row)
        session.commit()


def enable_ssl(
    project_name: str,
    hostname: str | None = None,
    email: str | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    current = settings or get_settings()
    project = get_project(validate_project_name(project_name), current)
    domains = list_domains(project.name, current)
    if not domains:
        raise SslError("Attach a domain before enabling HTTPS", status_code=409)
    if hostname:
        wanted = validate_domain(hostname)
        if not any(row.hostname == wanted for row in domains):
            raise DomainNotFoundError(f"Domain not found: {wanted}")
        selected = [row for row in domains if row.hostname == wanted]
        names = project_hostnames(selected)
        primary = wanted
    else:
        names = project_hostnames(domains)
        primary = domains[0].hostname
    stored_email = email or load_ssl_email(current)
    if not stored_email:
        raise SslError("An email address is required for Let's Encrypt notices", status_code=422)
    saved = save_ssl_email(stored_email, current)
    if current.nginx_dir is not None:
        _issue_local_certificate(primary, certificate_directory(primary, current))
    else:
        apply_project_nginx(project, domains, current)
        _issue_letsencrypt(saved, primary, names, current)
    assert project.id is not None
    _mark_ssl(project.id, True, current)
    domains = list_domains(project.name, current)
    applied = apply_project_nginx(project, domains, current)
    return {
        "project": project.name,
        "email": saved,
        "hostnames": names,
        "certificate": primary,
        "ssl": True,
        "mode": applied.get("mode"),
    }


def ssl_status(project_name: str, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    project = get_project(validate_project_name(project_name), current)
    domains = list_domains(project.name, current)
    return {
        "project": project.name,
        "email": load_ssl_email(current),
        "ssl": any(row.ssl_enabled for row in domains),
        "domains": [
            {"hostname": row.hostname, "www": row.www_enabled, "ssl": row.ssl_enabled}
            for row in domains
        ],
    }


def renew_certificates(settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    if current.nginx_dir is not None:
        return {"renewed": True, "mode": "local"}
    if not helper_available(current):
        raise SslError("Privileged helper is not installed", status_code=409)
    try:
        require_helper("ssl-renew", settings=current)
    except HelperError as exc:
        raise SslError(str(exc)) from exc
    return {"renewed": True, "mode": "helper"}
