from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import unquote

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.domains import DomainConflictError, claimed_hostnames
from vps_deployer.core.helper import HelperError, helper_available, require_helper
from vps_deployer.core.nginx import (
    CERTBOT_WEBROOT,
    LETSENCRYPT_LIVE,
    NginxError,
    certificate_directory,
)
from vps_deployer.core.ssl import (
    SslError,
    _issue_letsencrypt,
    _issue_local_certificate,
    load_ssl_email,
    save_ssl_email,
)
from vps_deployer.core.validation import (
    ValidationError,
    is_ipv4,
    validate_dashboard_host,
    validate_domain,
)

DASHBOARD_SITE_NAME = "vps-deployer.conf"
SESSION_COOKIE = "vps_deployer_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
PBKDF2_ROUNDS = 210_000
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "testserver", ""})
AUTH_EXEMPT_PATHS = frozenset({"/health", "/login", "/logout", "/api/github/webhook"})


class SessionCookieKwargs(TypedDict):
    httponly: bool
    samesite: Literal["lax"]
    secure: bool
    path: str
    max_age: int


class DashboardAccessError(RuntimeError):
    """Raised when public dashboard access cannot be configured."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DashboardState:
    hosts: list[str]
    ssl: bool
    password_hash: str
    session_secret: str

    @property
    def enabled(self) -> bool:
        return bool(self.hosts)

    @property
    def domain_hosts(self) -> list[str]:
        return [host for host in self.hosts if not is_ipv4(host)]

    @property
    def ip_hosts(self) -> list[str]:
        return [host for host in self.hosts if is_ipv4(host)]


def dashboard_state_path(settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    assert current.config_dir is not None
    return current.config_dir / "dashboard.json"


def load_dashboard_state(settings: Settings | None = None) -> DashboardState | None:
    path = dashboard_state_path(settings)
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    hosts = payload.get("hosts")
    password_hash = payload.get("password_hash")
    session_secret = payload.get("session_secret")
    if not isinstance(hosts, list) or not isinstance(password_hash, str):
        return None
    if not isinstance(session_secret, str) or not session_secret:
        return None
    cleaned: list[str] = []
    for item in hosts:
        if isinstance(item, str) and item:
            cleaned.append(item)
    return DashboardState(
        hosts=cleaned,
        ssl=bool(payload.get("ssl")),
        password_hash=password_hash,
        session_secret=session_secret,
    )


def _write_state(state: DashboardState, settings: Settings) -> None:
    settings.ensure_directories()
    path = dashboard_state_path(settings)
    path.write_text(
        json.dumps(
            {
                "hosts": state.hosts,
                "ssl": state.ssl,
                "password_hash": state.password_hash,
                "session_secret": state.session_secret,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o640)


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise DashboardAccessError("Dashboard password must be at least 8 characters", 422)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds_s, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def generate_password() -> str:
    return secrets.token_urlsafe(16)


def make_session_token(secret: str, now: int | None = None) -> str:
    expires = (now or int(time.time())) + SESSION_TTL_SECONDS
    signature = hmac.new(
        secret.encode("utf-8"),
        str(expires).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{expires}.{signature}"


def verify_session_token(secret: str, token: str, now: int | None = None) -> bool:
    expires_s, separator, signature = token.partition(".")
    if not separator or not expires_s.isdigit():
        return False
    expires = int(expires_s)
    if expires < (now or int(time.time())):
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        expires_s.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def request_host(host_header: str | None) -> str:
    raw = (host_header or "").strip().lower()
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end > 1 else raw
    return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw


def is_local_dashboard_host(host: str) -> bool:
    return host in LOCAL_HOSTS


def public_dashboard_hosts(settings: Settings | None = None) -> set[str]:
    state = load_dashboard_state(settings)
    if state is None:
        return set()
    return {host.lower() for host in state.hosts}


def is_public_dashboard_host(host: str, settings: Settings | None = None) -> bool:
    return host in public_dashboard_hosts(settings)


def path_is_auth_exempt(path: str) -> bool:
    if path in AUTH_EXEMPT_PATHS:
        return True
    return path.startswith("/static/")


def requires_dashboard_auth(
    host_header: str | None,
    path: str,
    settings: Settings | None = None,
) -> bool:
    if path_is_auth_exempt(path):
        return False
    host = request_host(host_header)
    if is_local_dashboard_host(host):
        return False
    return is_public_dashboard_host(host, settings)


def valid_session_cookie(token: str | None, settings: Settings | None = None) -> bool:
    state = load_dashboard_state(settings)
    if state is None or not token:
        return False
    return verify_session_token(state.session_secret, token)


def session_cookie_kwargs(settings: Settings | None = None) -> SessionCookieKwargs:
    state = load_dashboard_state(settings)
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": bool(state and state.ssl),
        "path": "/",
        "max_age": SESSION_TTL_SECONDS,
    }


def authenticate_dashboard(password: str, settings: Settings | None = None) -> str:
    state = load_dashboard_state(settings)
    if state is None or not state.password_hash:
        raise DashboardAccessError("Public dashboard password is not set", 409)
    if not verify_password(password, state.password_hash):
        raise DashboardAccessError("Invalid dashboard password", 401)
    return make_session_token(state.session_secret)


def safe_next_path(value: str | None) -> str:
    candidate = unquote((value or "").strip()) or "/"
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    return candidate


def dashboard_public_url(settings: Settings | None = None) -> str | None:
    state = load_dashboard_state(settings)
    if state is None or not state.hosts:
        return None
    preferred = state.domain_hosts[0] if state.domain_hosts else state.hosts[0]
    scheme = "https" if state.ssl and not is_ipv4(preferred) else "http"
    return f"{scheme}://{preferred}/"


def detect_public_ipv4() -> str:
    hostname = subprocess.run(
        ["hostname", "-I"],
        check=False,
        capture_output=True,
        text=True,
    )
    if hostname.returncode == 0:
        for token in hostname.stdout.split():
            try:
                return validate_dashboard_host(token)
            except ValidationError:
                continue
    route = subprocess.run(
        ["ip", "-4", "route", "get", "1.1.1.1"],
        check=False,
        capture_output=True,
        text=True,
    )
    if route.returncode == 0:
        parts = route.stdout.split()
        if "src" in parts:
            index = parts.index("src")
            if index + 1 < len(parts):
                return validate_dashboard_host(parts[index + 1])
    raise DashboardAccessError("Unable to detect a public IPv4 address", 409)


def _dashboard_proxy() -> list[str]:
    return [
        "    location / {",
        "        proxy_pass http://127.0.0.1:5100;",
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


def _http_server(hosts: list[str], *, redirect: bool) -> list[str]:
    names = " ".join(hosts)
    lines = [
        "server {",
        "    listen 80;",
        "    listen [::]:80;",
        f"    server_name {names};",
        "    client_max_body_size 32m;",
        *_acme_location(),
    ]
    if redirect:
        lines.extend(
            [
                "    location / {",
                "        return 301 https://$host$request_uri;",
                "    }",
            ]
        )
    else:
        lines.extend(_dashboard_proxy())
    lines.append("}")
    return lines


def render_dashboard_nginx(
    hosts: list[str],
    *,
    ssl: bool = False,
    ssl_cert_dir: Path | None = None,
) -> str:
    if not hosts:
        raise DashboardAccessError("At least one hostname or IPv4 address is required", 422)
    cleaned = [validate_dashboard_host(host) for host in hosts]
    domains = [host for host in cleaned if not is_ipv4(host)]
    ips = [host for host in cleaned if is_ipv4(host)]
    lines = [
        "# vps-deployer site: dashboard",
        "# Managed by VPS Deployer. Do not edit by hand.",
    ]
    if ssl and domains:
        lines.extend(_http_server(domains, redirect=True))
        if ips:
            lines.append("")
            lines.extend(_http_server(ips, redirect=False))
        primary = domains[0]
        cert_dir = ssl_cert_dir or (LETSENCRYPT_LIVE / primary)
        lines.extend(
            [
                "",
                "server {",
                "    listen 443 ssl;",
                "    listen [::]:443 ssl;",
                f"    server_name {' '.join(domains)};",
                "    client_max_body_size 32m;",
                f"    ssl_certificate {cert_dir}/fullchain.pem;",
                f"    ssl_certificate_key {cert_dir}/privkey.pem;",
                "    ssl_protocols TLSv1.2 TLSv1.3;",
                *_dashboard_proxy(),
                "}",
            ]
        )
    else:
        lines.extend(_http_server(cleaned, redirect=False))
    lines.append("")
    return "\n".join(lines)


def _assert_hosts_available(hosts: list[str], settings: Settings) -> list[str]:
    cleaned: list[str] = []
    taken = claimed_hostnames(settings)
    for host in hosts:
        name = validate_dashboard_host(host)
        if name in taken:
            raise DomainConflictError(f"Domain already in use: {name}")
        if name in cleaned:
            continue
        cleaned.append(name)
    if not cleaned:
        raise DashboardAccessError("At least one hostname or IPv4 address is required", 422)
    return cleaned


def _apply_dashboard_nginx(state: DashboardState, settings: Settings) -> dict[str, object]:
    ssl_cert_dir = None
    domains = state.domain_hosts
    if state.ssl and domains:
        if settings.nginx_dir is not None:
            ssl_cert_dir = certificate_directory(domains[0], settings)
        else:
            ssl_cert_dir = LETSENCRYPT_LIVE / domains[0]
    config = render_dashboard_nginx(state.hosts, ssl=state.ssl, ssl_cert_dir=ssl_cert_dir)
    if settings.nginx_dir is not None:
        settings.nginx_dir.mkdir(parents=True, exist_ok=True)
        path = settings.nginx_dir / DASHBOARD_SITE_NAME
        path.write_text(config, encoding="utf-8")
        return {"applied": True, "mode": "local", "path": str(path)}
    if not helper_available(settings):
        raise NginxError("Privileged helper is not installed")
    try:
        require_helper("dashboard-site-install", settings=settings, stdin=config)
    except HelperError as exc:
        raise NginxError(str(exc)) from exc
    return {"applied": True, "mode": "helper"}


def _remove_dashboard_nginx(settings: Settings) -> None:
    if settings.nginx_dir is not None:
        path = settings.nginx_dir / DASHBOARD_SITE_NAME
        path.unlink(missing_ok=True)
        return
    if not helper_available(settings):
        return
    try:
        require_helper("dashboard-site-remove", settings=settings)
    except HelperError as exc:
        raise NginxError(str(exc)) from exc


def enable_dashboard_access(
    *,
    hosts: list[str],
    password: str | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    current = settings or get_settings()
    cleaned = _assert_hosts_available(hosts, current)
    existing = load_dashboard_state(current)
    generated: str | None = None
    if password:
        password_hash = hash_password(password)
    elif existing is not None and existing.password_hash:
        password_hash = existing.password_hash
    else:
        generated = generate_password()
        password_hash = hash_password(generated)
    session_secret = existing.session_secret if existing is not None else secrets.token_urlsafe(32)
    state = DashboardState(
        hosts=cleaned,
        ssl=bool(existing and existing.ssl and any(not is_ipv4(item) for item in cleaned)),
        password_hash=password_hash,
        session_secret=session_secret,
    )
    if state.ssl and not state.domain_hosts:
        state.ssl = False
    _write_state(state, current)
    applied = _apply_dashboard_nginx(state, current)
    payload: dict[str, object] = {
        "enabled": True,
        "hosts": state.hosts,
        "ssl": state.ssl,
        "url": dashboard_public_url(current),
        "mode": applied.get("mode"),
    }
    if generated is not None:
        payload["password"] = generated
    return payload


def disable_dashboard_access(settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    existing = load_dashboard_state(current)
    _remove_dashboard_nginx(current)
    if existing is not None:
        existing.hosts = []
        existing.ssl = False
        _write_state(existing, current)
    return {"enabled": False, "hosts": []}


def set_dashboard_password(password: str, settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    existing = load_dashboard_state(current)
    if existing is None:
        existing = DashboardState(
            hosts=[],
            ssl=False,
            password_hash=hash_password(password),
            session_secret=secrets.token_urlsafe(32),
        )
    else:
        existing.password_hash = hash_password(password)
    _write_state(existing, current)
    return {"updated": True, "enabled": existing.enabled}


def enable_dashboard_ssl(
    email: str | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    current = settings or get_settings()
    state = load_dashboard_state(current)
    if state is None or not state.hosts:
        raise DashboardAccessError("Enable the public dashboard before HTTPS", 409)
    if not state.domain_hosts:
        raise DashboardAccessError(
            "Let's Encrypt needs a hostname. IP-only access stays HTTP.",
            409,
        )
    if not state.password_hash:
        raise DashboardAccessError("Set a dashboard password before enabling HTTPS", 409)
    stored_email = email or load_ssl_email(current)
    if not stored_email:
        raise SslError("An email address is required for Let's Encrypt notices", status_code=422)
    saved = save_ssl_email(stored_email, current)
    primary = state.domain_hosts[0]
    names = [validate_domain(host) for host in state.domain_hosts]
    if current.nginx_dir is not None:
        _issue_local_certificate(primary, certificate_directory(primary, current))
    else:
        _apply_dashboard_nginx(state, current)
        _issue_letsencrypt(saved, primary, names, current)
    state.ssl = True
    _write_state(state, current)
    applied = _apply_dashboard_nginx(state, current)
    return {
        "ssl": True,
        "email": saved,
        "hostnames": names,
        "certificate": primary,
        "url": dashboard_public_url(current),
        "mode": applied.get("mode"),
    }


def dashboard_status(settings: Settings | None = None) -> dict[str, object]:
    current = settings or get_settings()
    state = load_dashboard_state(current)
    return {
        "enabled": bool(state and state.enabled),
        "hosts": state.hosts if state else [],
        "ssl": bool(state and state.ssl),
        "url": dashboard_public_url(current),
        "password_set": bool(state and state.password_hash),
    }
