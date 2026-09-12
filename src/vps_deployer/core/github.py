from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt
from sqlmodel import Session, select

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.db.models import GitHubInstallation
from vps_deployer.db.session import get_engine, init_db

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "VPS-Deployer"
PRIVATE_KEY_NAME = "github-app.pem"
WEBHOOK_SECRET_NAME = "github-webhook-secret"
META_NAME = "github.json"


class GitHubNotConfiguredError(RuntimeError):
    """Raised when GitHub App files are missing on this VPS."""


class GitHubAuthError(RuntimeError):
    """Raised when GitHub App authentication fails."""


class WebhookError(ValueError):
    """Raised when a webhook is missing, invalid, or not applicable."""

    def __init__(self, message: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class GitHubSettings:
    app_id: str
    installation_id: str | None
    private_key_path: Path
    webhook_secret_path: Path


def _config_dir(settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    current.ensure_directories()
    assert current.config_dir is not None
    return current.config_dir


def _write_secret_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def github_paths(settings: Settings | None = None) -> tuple[Path, Path, Path]:
    directory = _config_dir(settings)
    return directory / PRIVATE_KEY_NAME, directory / WEBHOOK_SECRET_NAME, directory / META_NAME


def is_github_configured(settings: Settings | None = None) -> bool:
    key, secret, meta = github_paths(settings)
    return key.is_file() and secret.is_file() and meta.is_file()


def load_github_settings(settings: Settings | None = None) -> GitHubSettings:
    key, secret, meta = github_paths(settings)
    if not key.is_file() or not secret.is_file() or not meta.is_file():
        raise GitHubNotConfiguredError("GitHub App is not configured on this VPS")
    payload = json.loads(meta.read_text(encoding="utf-8"))
    app_id = str(payload.get("app_id") or "").strip()
    installation_id = payload.get("installation_id")
    installation = str(installation_id).strip() if installation_id else None
    if not app_id:
        raise GitHubNotConfiguredError("GitHub App ID is missing")
    return GitHubSettings(
        app_id=app_id,
        installation_id=installation or None,
        private_key_path=key,
        webhook_secret_path=secret,
    )


def read_webhook_secret(settings: Settings | None = None) -> str:
    configured = load_github_settings(settings)
    secret = configured.webhook_secret_path.read_text(encoding="utf-8").strip()
    if not secret:
        raise GitHubNotConfiguredError("GitHub webhook secret is empty")
    return secret


def _read_private_key(path: Path) -> str:
    pem = path.read_text(encoding="utf-8")
    if "PRIVATE KEY" not in pem:
        raise GitHubAuthError("GitHub private key file is not a PEM private key")
    return pem


def configure_github(
    app_id: str,
    private_key: str,
    webhook_secret: str,
    installation_id: str | None = None,
    settings: Settings | None = None,
) -> GitHubSettings:
    app_id = app_id.strip()
    webhook_secret = webhook_secret.strip()
    installation = installation_id.strip() if installation_id else None
    if not app_id.isdigit():
        raise ValueError("GitHub App ID must be numeric")
    if len(webhook_secret) < 8:
        raise ValueError("Webhook secret must be at least 8 characters")
    if "PRIVATE KEY" not in private_key:
        raise ValueError("Private key must be a PEM private key")

    key_path, secret_path, meta_path = github_paths(settings)
    _write_secret_file(key_path, private_key if private_key.endswith("\n") else private_key + "\n")
    _write_secret_file(secret_path, webhook_secret + "\n")
    meta_path.write_text(
        json.dumps({"app_id": app_id, "installation_id": installation}, indent=2) + "\n",
        encoding="utf-8",
    )
    meta_path.chmod(0o600)
    _record_installation(app_id, installation, settings)
    return load_github_settings(settings)


def _record_installation(
    app_id: str, installation_id: str | None, settings: Settings | None
) -> None:
    current = settings or get_settings()
    init_db(current)
    with Session(get_engine(current)) as session:
        row = session.exec(select(GitHubInstallation)).first()
        if row is None:
            row = GitHubInstallation()
            session.add(row)
        row.app_id = app_id
        row.installation_id = installation_id
        row.configured = True
        row.webhook_path = "/api/github/webhook"
        session.commit()


def create_app_jwt(settings: Settings | None = None, now: int | None = None) -> str:
    configured = load_github_settings(settings)
    issued = (now if now is not None else int(time.time())) - 60
    payload = {
        "iat": issued,
        "exp": issued + 9 * 60,
        "iss": configured.app_id,
    }
    return jwt.encode(payload, _read_private_key(configured.private_key_path), algorithm="RS256")


def call_github(
    method: str,
    path: str,
    token: str,
    json_body: dict[str, Any] | None = None,
) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": USER_AGENT,
    }
    url = f"{GITHUB_API}{path}"
    try:
        response = httpx.request(method, url, headers=headers, json=json_body, timeout=10.0)
    except httpx.HTTPError as exc:
        raise GitHubAuthError("Unable to reach GitHub") from exc
    if response.status_code >= 400:
        raise GitHubAuthError(f"GitHub API returned HTTP {response.status_code}")
    if not response.content:
        return None
    return response.json()


def authenticate_app(settings: Settings | None = None) -> dict[str, Any]:
    token = create_app_jwt(settings)
    payload = call_github("GET", "/app", token)
    if not isinstance(payload, dict):
        raise GitHubAuthError("Unexpected GitHub App response")
    return payload


def resolve_installation_id(settings: Settings | None = None) -> str:
    configured = load_github_settings(settings)
    if configured.installation_id:
        return configured.installation_id
    token = create_app_jwt(settings)
    payload = call_github("GET", "/app/installations", token)
    if not isinstance(payload, list) or not payload:
        raise GitHubAuthError("No GitHub App installations found")
    if len(payload) > 1:
        raise GitHubAuthError("Multiple installations found. Pass --installation-id")
    first = payload[0]
    if not isinstance(first, dict) or first.get("id") is None:
        raise GitHubAuthError("GitHub installation response was invalid")
    installation_id = str(first["id"])
    configure_github(
        app_id=configured.app_id,
        private_key=_read_private_key(configured.private_key_path),
        webhook_secret=read_webhook_secret(settings),
        installation_id=installation_id,
        settings=settings,
    )
    return installation_id


def create_installation_token(settings: Settings | None = None) -> str:
    installation_id = resolve_installation_id(settings)
    token = create_app_jwt(settings)
    payload = call_github("POST", f"/app/installations/{installation_id}/access_tokens", token)
    if not isinstance(payload, dict) or not payload.get("token"):
        raise GitHubAuthError("GitHub did not return an installation token")
    return str(payload["token"])


def list_accessible_repositories(settings: Settings | None = None) -> list[dict[str, str]]:
    token = create_installation_token(settings)
    payload = call_github("GET", "/installation/repositories", token)
    if not isinstance(payload, dict):
        raise GitHubAuthError("Unexpected repository list from GitHub")
    repositories = payload.get("repositories", [])
    if not isinstance(repositories, list):
        raise GitHubAuthError("Unexpected repository list from GitHub")
    result: list[dict[str, str]] = []
    for item in repositories:
        if not isinstance(item, dict):
            continue
        full_name = item.get("full_name")
        default_branch = item.get("default_branch") or "main"
        if isinstance(full_name, str) and full_name:
            result.append(
                {
                    "repository": full_name,
                    "default_branch": str(default_branch),
                }
            )
    return result


def github_status(settings: Settings | None = None, probe: bool = True) -> dict[str, Any]:
    if not is_github_configured(settings):
        return {
            "configured": False,
            "authenticated": False,
            "app_id": None,
            "installation_id": None,
            "webhook_path": "/api/github/webhook",
            "app_name": None,
            "error": "GitHub App is not configured",
        }
    configured = load_github_settings(settings)
    status: dict[str, Any] = {
        "configured": True,
        "authenticated": False,
        "app_id": configured.app_id,
        "installation_id": configured.installation_id,
        "webhook_path": "/api/github/webhook",
        "app_name": None,
        "error": None,
    }
    if not probe:
        return status
    try:
        app = authenticate_app(settings)
        status["authenticated"] = True
        status["app_name"] = app.get("name")
        if not configured.installation_id:
            status["installation_id"] = resolve_installation_id(settings)
    except (GitHubAuthError, GitHubNotConfiguredError) as exc:
        status["error"] = str(exc)
    return status


def verify_webhook_signature(body: bytes, signature_header: str | None, secret: str) -> None:
    if not signature_header:
        raise WebhookError("Missing X-Hub-Signature-256", 401)
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookError("Invalid webhook signature", 401)


def handle_github_webhook(
    body: bytes,
    signature_header: str | None,
    event: str | None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    from vps_deployer.core.deployments import queue_push_event
    from vps_deployer.core.projects import ProjectNotFoundError

    secret = read_webhook_secret(settings)
    verify_webhook_signature(body, signature_header, secret)
    if event == "ping":
        return {"accepted": True, "event": "ping", "queued": []}
    if event != "push":
        raise WebhookError("Unsupported GitHub event", 400)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookError("Webhook payload is not valid JSON", 400) from exc
    if not isinstance(payload, dict):
        raise WebhookError("Webhook payload is not an object", 400)
    repository, branch, commit = parse_push_payload(payload)
    try:
        queued = queue_push_event(repository, branch, commit, settings)
        from vps_deployer.core.engine import notify_worker

        notify_worker()
    except ProjectNotFoundError as exc:
        raise WebhookError(str(exc), 404) from exc
    except ValueError as exc:
        raise WebhookError(str(exc), 400) from exc
    return {
        "accepted": True,
        "event": "push",
        "repository": repository,
        "branch": branch,
        "commit_sha": commit,
        "queued": [row.id for row in queued],
        "status": "QUEUED",
    }


def parse_push_payload(payload: dict[str, Any]) -> tuple[str, str, str]:
    repository = payload.get("repository")
    if not isinstance(repository, dict):
        raise WebhookError("Webhook payload is missing repository", 400)
    full_name = repository.get("full_name")
    if not isinstance(full_name, str) or "/" not in full_name:
        raise WebhookError("Webhook payload has an invalid repository", 400)
    ref = payload.get("ref")
    if not isinstance(ref, str) or not ref.startswith("refs/heads/"):
        raise WebhookError("Unsupported git ref", 400)
    branch = ref.removeprefix("refs/heads/")
    commit = payload.get("after")
    if not isinstance(commit, str) or not commit or set(commit) == {"0"}:
        raise WebhookError("Webhook payload has no commit", 400)
    return full_name, branch, commit
