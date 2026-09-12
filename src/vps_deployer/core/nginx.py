from __future__ import annotations

from pathlib import Path

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.helper import HelperError, helper_available, require_helper
from vps_deployer.core.validation import (
    APPS_ROOT,
    PORT_RANGE,
    validate_domain,
    validate_port,
    validate_project_name,
)
from vps_deployer.db.models import Domain, Project

STATIC_RUNTIMES = frozenset({"static", "vite"})
LETSENCRYPT_LIVE = Path("/etc/letsencrypt/live")
CERTBOT_WEBROOT = Path("/var/www/certbot")


class NginxError(RuntimeError):
    """Raised when an nginx site cannot be rendered or applied."""


def site_filename(project_name: str) -> str:
    return f"vps-deployer-{validate_project_name(project_name)}.conf"


def site_names(domain: Domain) -> list[str]:
    hostname = validate_domain(domain.hostname)
    names = [hostname]
    if domain.www_enabled and not hostname.startswith("www."):
        names.append(f"www.{hostname}")
    return names


def project_hostnames(domains: list[Domain]) -> list[str]:
    names: list[str] = []
    for domain in domains:
        names.extend(site_names(domain))
    return names


def _static_root(project: Project, apps_root: Path) -> Path:
    base = apps_root / project.name / "current"
    if project.runtime == "vite":
        return base / "dist"
    return base


def _app_location(project: Project, apps_root: Path) -> list[str]:
    if project.runtime in STATIC_RUNTIMES:
        static_root = _static_root(project, apps_root)
        return [
            f"    root {static_root};",
            "    location / {",
            "        try_files $uri $uri/ /index.html;",
            "    }",
        ]
    port = validate_port(project.port)
    if port not in PORT_RANGE:
        raise NginxError("Application port is outside the reserved range")
    return [
        "    location / {",
        f"        proxy_pass http://127.0.0.1:{port};",
        "        proxy_http_version 1.1;",
        "        proxy_set_header Host $host;",
        "        proxy_set_header X-Real-IP $remote_addr;",
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        "        proxy_set_header Upgrade $http_upgrade;",
        '        proxy_set_header Connection "upgrade";',
        "    }",
    ]


def _acme_location() -> list[str]:
    return [
        "    location /.well-known/acme-challenge/ {",
        f"        root {CERTBOT_WEBROOT};",
        "    }",
    ]


def certificate_directory(hostname: str, settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    name = validate_domain(hostname)
    if current.nginx_dir is not None:
        base = current.ssl_dir or (current.nginx_dir / "certs")
        return base / name
    return LETSENCRYPT_LIVE / name


def render_nginx_site(
    project: Project,
    domains: list[Domain],
    *,
    apps_root: Path | None = None,
    ssl_cert_dir: Path | None = None,
) -> str:
    name = validate_project_name(project.name)
    if not domains:
        raise NginxError("Cannot render an nginx site without a domain")
    hostnames = project_hostnames(domains)
    if not hostnames:
        raise NginxError("Cannot render an nginx site without a hostname")
    root = apps_root or APPS_ROOT
    server_name = " ".join(hostnames)
    use_ssl = any(domain.ssl_enabled for domain in domains)
    lines = [
        f"# vps-deployer site: {name}",
        "# Managed by VPS Deployer. Do not edit by hand.",
        "server {",
        "    listen 80;",
        "    listen [::]:80;",
        f"    server_name {server_name};",
        "    client_max_body_size 32m;",
        *_acme_location(),
    ]
    if use_ssl:
        lines.extend(
            [
                "    location / {",
                "        return 301 https://$host$request_uri;",
                "    }",
            ]
        )
    else:
        lines.extend(_app_location(project, root))
    lines.append("}")
    if use_ssl:
        primary = next(domain.hostname for domain in domains if domain.ssl_enabled)
        cert_dir = ssl_cert_dir or (LETSENCRYPT_LIVE / primary)
        lines.extend(
            [
                "",
                "server {",
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {server_name};",
                "    client_max_body_size 32m;",
                f"    ssl_certificate {cert_dir}/fullchain.pem;",
                f"    ssl_certificate_key {cert_dir}/privkey.pem;",
                "    ssl_protocols TLSv1.2 TLSv1.3;",
                *_app_location(project, root),
                "}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _local_site_path(settings: Settings, project_name: str) -> Path:
    assert settings.nginx_dir is not None
    return settings.nginx_dir / site_filename(project_name)


def apply_project_nginx(
    project: Project,
    domains: list[Domain],
    settings: Settings | None = None,
) -> dict[str, object]:
    current = settings or get_settings()
    name = validate_project_name(project.name)
    if not domains:
        return remove_project_nginx(project, current)
    apps_root = current.apps_root if current.nginx_dir is not None else APPS_ROOT
    assert apps_root is not None
    ssl_cert_dir = None
    if any(domain.ssl_enabled for domain in domains):
        primary = next(domain.hostname for domain in domains if domain.ssl_enabled)
        if current.nginx_dir is not None:
            ssl_cert_dir = certificate_directory(primary, current)
        else:
            ssl_cert_dir = LETSENCRYPT_LIVE / primary
    config = render_nginx_site(project, domains, apps_root=apps_root, ssl_cert_dir=ssl_cert_dir)
    if current.nginx_dir is not None:
        current.nginx_dir.mkdir(parents=True, exist_ok=True)
        path = _local_site_path(current, name)
        path.write_text(config, encoding="utf-8")
        return {
            "applied": True,
            "mode": "local",
            "path": str(path),
            "domains": len(domains),
            "ssl": any(domain.ssl_enabled for domain in domains),
        }
    if not helper_available(current):
        raise NginxError("Privileged helper is not installed")
    try:
        require_helper("nginx-site-install", name, settings=current, stdin=config)
    except HelperError as exc:
        raise NginxError(str(exc)) from exc
    return {
        "applied": True,
        "mode": "helper",
        "domains": len(domains),
        "ssl": any(domain.ssl_enabled for domain in domains),
    }


def remove_project_nginx(project: Project, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    name = validate_project_name(project.name)
    if current.nginx_dir is not None:
        path = _local_site_path(current, name)
        path.unlink(missing_ok=True)
        return {"applied": True, "mode": "local", "removed": True}
    if not helper_available(current):
        return {"applied": False, "mode": "helper", "removed": False}
    try:
        require_helper("nginx-site-remove", name, settings=current)
    except HelperError as exc:
        raise NginxError(str(exc)) from exc
    return {"applied": True, "mode": "helper", "removed": True}
