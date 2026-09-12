from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from vps_deployer.core.config import reset_settings
from vps_deployer.db.session import reset_engine


def make_github_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    monkeypatch.setenv("VPS_DEPLOYER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VPS_DEPLOYER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VPS_DEPLOYER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VPS_DEPLOYER_DATABASE_PATH", str(tmp_path / "data" / "vps-deployer.db"))
    monkeypatch.setenv("VPS_DEPLOYER_CREATE_TABLES", "true")
    monkeypatch.setenv("VPS_DEPLOYER_API_HOST", "127.0.0.1")
    monkeypatch.setenv("VPS_DEPLOYER_API_PORT", "51999")
    monkeypatch.setenv("VPS_DEPLOYER_APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.setenv("VPS_DEPLOYER_GIT_CLONE_BASE", str(tmp_path / "git"))
    monkeypatch.setenv("VPS_DEPLOYER_WORKER_ENABLED", "false")
    monkeypatch.setenv("VPS_DEPLOYER_RELEASE_RETENTION", "5")
    monkeypatch.setenv("VPS_DEPLOYER_RUNTIME", "process")
    monkeypatch.setenv("VPS_DEPLOYER_HELPER_SUDO", "false")
    monkeypatch.setenv("VPS_DEPLOYER_NGINX_DIR", str(tmp_path / "nginx"))
    monkeypatch.setenv("VPS_DEPLOYER_SSL_DIR", str(tmp_path / "ssl"))
    monkeypatch.setenv("VPS_DEPLOYER_SSL_EMAIL", "ops@example.com")
    reset_settings()
    reset_engine()
    yield tmp_path
    reset_settings()
    reset_engine()


@pytest.fixture
def client(tmp_env: Path) -> Generator[TestClient, None, None]:
    from vps_deployer.api.main import app

    with TestClient(app) as test_client:
        yield test_client
