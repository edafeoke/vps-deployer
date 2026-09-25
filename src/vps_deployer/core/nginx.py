from __future__ import annotations

import re
from pathlib import Path

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.helper import HelperError, helper_available, require_helper
from vps_deployer.core.host_admin import HostError, config_metadata
from vps_deployer.core.site_config import load_site_config, save_site_config, site_mutation
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


def _host_call(action: str, payload: dict, settings: Settings) -> dict:
    from vps_deployer.core.host import _call

    try:
        return _call(action, payload, settings)
    except HostError as exc:
        raise NginxError(str(exc)) from exc


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
    certificate: str | None = None,
    certificate_key: str | None = None,
) -> str:
    name = validate_project_name(project.name)
    if not domains:
        raise NginxError("Cannot render an nginx site without a domain")
    hostnames = project_hostnames(domains)
    if not hostnames:
        raise NginxError("Cannot render an nginx site without a hostname")
    root = apps_root or APPS_ROOT
    server_name = " ".join(hostnames)
    use_ssl = bool(certificate) or any(domain.ssl_enabled for domain in domains)
    lines = [
        f"# vps-deployer site: {name}",
        "# Managed by VPS Deployer. Use the dashboard or nginx edit command.",
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
        primary = next((d.hostname for d in domains if d.ssl_enabled), domains[0].hostname)
        cert_dir = ssl_cert_dir or (LETSENCRYPT_LIVE / primary)
        lines.extend(
            [
                "",
                "server {",
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {server_name};",
                "    client_max_body_size 32m;",
                f"    ssl_certificate {certificate or str(cert_dir / 'fullchain.pem')};",
                f"    ssl_certificate_key {certificate_key or str(cert_dir / 'privkey.pem')};",
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


@site_mutation
def apply_project_nginx(
    project: Project,
    domains: list[Domain],
    settings: Settings | None = None,
    *,
    state: dict[str, str] | None = None,
) -> dict[str, object]:
    current = settings or get_settings()
    name = validate_project_name(project.name)
    bound = load_site_config(name, current).get("host_config_id")
    if bound:
        return {
            "applied": False,
            "preserved": True,
            "host_config_id": bound,
            "domains": len(domains),
        }
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
    selected = load_site_config(name, current) if state is None else state
    if selected.get("disabled"):
        return {"applied": False, "disabled": True, "domains": len(domains)}
    config = selected.get("custom") or render_nginx_site(
        project,
        domains,
        apps_root=apps_root,
        ssl_cert_dir=ssl_cert_dir,
        certificate=selected.get("certificate"),
        certificate_key=selected.get("certificate_key"),
    )
    result = install_project_config(project, config, current)
    result["domains"] = len(domains)
    return result


def install_project_config(project: Project, config: str, current: Settings) -> dict[str, object]:
    name = validate_project_name(project.name)
    if current.nginx_dir is not None:
        current.nginx_dir.mkdir(parents=True, exist_ok=True)
        path = _local_site_path(current, name)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(config, encoding="utf-8")
        temporary.replace(path)
        return {
            "applied": True,
            "mode": "local",
            "path": str(path),
            "ssl": "ssl_certificate " in config,
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
        "ssl": "ssl_certificate " in config,
    }


def nginx_status(project_name: str, settings: Settings | None = None) -> dict[str, object]:
    from vps_deployer.core.domains import list_domains
    from vps_deployer.core.projects import get_project

    current = settings or get_settings()
    project = get_project(project_name, current)
    domains = list_domains(project.name, current)
    state = load_site_config(project.name, current)
    error = None
    content = ""
    path = str(_local_site_path(current, project.name)) if current.nginx_dir else None
    try:
        if state.get("host_config_id"):
            item = _host_call("host-nginx-read", {"id": state["host_config_id"]}, current)
            path, content = item["path"], item["content"]
        elif current.nginx_dir is not None:
            site = _local_site_path(current, project.name)
            content = site.read_text(encoding="utf-8") if site.exists() else ""
        elif helper_available(current):
            result = require_helper("nginx-site-read", project.name, settings=current)
            path, _, content = result.stdout.partition("\n")
        else:
            error = "Privileged helper is not installed"
    except (OSError, HelperError, HostError, NginxError) as exc:
        error = str(exc)
    active = bool(content)
    if not content and domains:
        assert current.apps_root is not None
        primary = next((d.hostname for d in domains if d.ssl_enabled), domains[0].hostname)
        content = state.get("custom") or render_nginx_site(
            project,
            domains,
            apps_root=current.apps_root,
            ssl_cert_dir=certificate_directory(primary, current),
            certificate=state.get("certificate"),
            certificate_key=state.get("certificate_key"),
        )

    def directives(key: str) -> list[str]:
        return re.findall(rf"^\s*{key}\s+([^;]+);\s*$", content, re.MULTILINE)

    deployment = Path(project.deployment_path)
    return {
        "project": project.name,
        "path": path,
        "content": content,
        "installed": active,
        "custom": bool(state.get("custom") or state.get("host_config_id")),
        "transferred_config": state.get("host_config_id"),
        "error": error,
        "deployment_path": str(deployment),
        "current_path": str(deployment / "current"),
        "release_path": str((deployment / "current").resolve())
        if (deployment / "current").exists()
        else None,
        "roots": directives("root"),
        "upstreams": directives("proxy_pass"),
        "certificates": directives("ssl_certificate"),
        "certificate_keys": directives("ssl_certificate_key"),
    }


@site_mutation
def save_nginx_config(
    name: str,
    content: str | None,
    settings: Settings | None = None,
) -> dict[str, object]:
    from vps_deployer.core.domains import list_domains
    from vps_deployer.core.projects import get_project
    from vps_deployer.core.validation import ValidationError

    current = settings or get_settings()
    project = get_project(name, current)
    domains = list_domains(name, current)
    state = load_site_config(name, current)
    if state.get("host_config_id"):
        if content is None:
            raise ValidationError(
                "Transferred sites cannot be reset to a generated config; use the Nginx editor"
            )
        item = _host_call("host-nginx-read", {"id": state["host_config_id"]}, current)
        if set(config_metadata(content)["domains"]) != set(item["domains"]):
            raise ValidationError(
                "Keep transferred server_name declarations to preserve domain ownership"
            )
        _host_call(
            "host-nginx-action",
            {
                "id": item["id"],
                "revision": item["revision"],
                "content": content,
                "action": "save-reload",
            },
            current,
        )
        return nginx_status(name, current)
    if not domains:
        raise ValidationError("Attach a domain before configuring Nginx")
    state = load_site_config(name, current)
    if content is None:
        state.pop("custom", None)
        state.pop("disabled", None)
    else:
        # Browsers submit textarea newlines as CRLF; Nginx files use LF.
        content = content.replace("\r\n", "\n")
        validate_custom_config(project, domains, content, current)
        state["custom"] = content
    apply_project_nginx(project, domains, current, state=state)
    save_site_config(name, state, current)
    return nginx_status(name, current)


def validate_custom_config(
    project: Project,
    domains: list[Domain],
    content: str,
    settings: Settings,
) -> None:
    """Restrict edits to the generated site's hosts, upstream and certificate paths."""
    from vps_deployer.core.validation import ValidationError

    if not content.strip() or len(content) > 12000 or any(c in content for c in ("\x00", "\r")):
        raise ValidationError("Nginx config must contain 1–12000 characters")
    assert settings.apps_root is not None
    primary = next((d.hostname for d in domains if d.ssl_enabled), domains[0].hostname)
    state = load_site_config(project.name, settings)
    generated = render_nginx_site(
        project,
        domains,
        apps_root=settings.apps_root,
        ssl_cert_dir=certificate_directory(primary, settings),
        certificate=state.get("certificate"),
        certificate_key=state.get("certificate_key"),
    )
    allowed = {line.strip() for line in generated.splitlines() if line.strip()}
    stack: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if len(line) > 500:
            raise ValidationError("Nginx lines must not exceed 500 characters")
        if not stripped or stripped.startswith("#"):
            continue
        if stripped not in allowed and not re.fullmatch(
            r"(?:client_max_body_size [1-9][0-9]{0,3}[mk]|"
            r"(?:proxy_read_timeout|proxy_connect_timeout|proxy_send_timeout) [1-9][0-9]{0,3}s);",
            stripped,
        ):
            raise ValidationError(f"Unsupported Nginx directive: {stripped}")
        if stripped == "server {":
            if stack:
                raise ValidationError("Server blocks cannot be nested")
            stack.append("server")
        elif stripped.startswith("location "):
            if stack != ["server"]:
                raise ValidationError("Locations must be inside a server block")
            stack.append("location")
        elif stripped == "}":
            if not stack:
                raise ValidationError("Unbalanced Nginx braces")
            stack.pop()
        elif not stack:
            raise ValidationError("Directives must be inside a server block")
    if stack or f"# vps-deployer site: {project.name}" not in content.splitlines():
        raise ValidationError("Unbalanced Nginx braces or missing project marker")
    # Keep routing/TLS declarations intact; edits tune request limits and proxy timeouts.
    for directive in (
        "listen",
        "server_name",
        "root",
        "proxy_pass",
        "ssl_certificate",
        "ssl_certificate_key",
        "ssl_protocols",
    ):
        pattern = rf"^\s*{directive}\s+[^;]+;\s*$"
        expected = sorted(s.strip() for s in re.findall(pattern, generated, re.MULTILINE))
        actual = sorted(s.strip() for s in re.findall(pattern, content, re.MULTILINE))
        if expected != actual:
            raise ValidationError(
                f"Keep generated {directive} declarations; use domains/SSL controls"
            )


def remove_project_nginx(project: Project, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    name = validate_project_name(project.name)
    state = load_site_config(name, current)
    if state.get("host_config_id"):
        item = _host_call("host-nginx-read", {"id": state["host_config_id"]}, current)
        return _host_call(
            "host-nginx-action",
            {"id": item["id"], "revision": item["revision"], "action": "delete"},
            current,
        )
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
