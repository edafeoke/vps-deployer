from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from vps_deployer.core.config import get_settings
from vps_deployer.core.helper import HelperError
from vps_deployer.core.nginx import NginxError, save_nginx_config
from vps_deployer.core.site_config import load_site_config


def create_site(client: TestClient) -> None:
    result = client.post(
        "/api/projects",
        json={
            "name": "my-app",
            "repository": "example/my-app",
            "domain": "example.com",
        },
    )
    assert result.status_code == 201, result.text


def certificate_files(tmp_env: Path, *, hosts=None, expired=False, mismatch=False):
    base = tmp_env / "ssl" / "my-app"
    base.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "example.com")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now + timedelta(days=-1 if expired else 30))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(host) for host in (hosts or ["example.com", "*.example.com"])]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = base / "origin.pem", base / "origin.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    if mismatch:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return {"certificate": str(cert_path), "certificate_key": str(key_path)}


def test_nginx_edit_persists_and_resets(client: TestClient):
    create_site(client)
    url = "/api/projects/my-app/nginx"
    original = client.get(url).json()
    assert original["installed"]
    assert original["current_path"].endswith("/my-app/current")
    assert original["upstreams"]
    content = (
        original["content"]
        .replace("32m;", "64m;")
        .replace(
            "proxy_http_version 1.1;", "proxy_http_version 1.1;\n        proxy_read_timeout 120s;"
        )
    )
    saved = client.put(url, json={"content": content})
    assert saved.status_code == 200, saved.text
    assert saved.json()["custom"]
    assert client.post(url).status_code == 200
    assert client.get(url).json()["content"] == content
    assert (
        client.post(
            "/api/projects/my-app/domains", json={"hostname": "new.example.com"}
        ).status_code
        == 422
    )
    assert client.post("/api/projects/my-app/ssl").status_code == 422
    assert len(client.get("/api/projects/my-app/domains").json()["domains"]) == 1
    reset = client.delete(url)
    assert reset.status_code == 200
    assert not reset.json()["custom"]
    assert reset.json()["content"] == original["content"]


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s + "include /etc/passwd;\n",
        lambda s: s.replace("example.com", "other.example.com"),
        lambda s: s.replace("listen 80;", "listen 5100;"),
        lambda s: s + "}\n",
        lambda s: s.replace("server {", "server {\nserver {"),
        lambda s: s.replace("root /var/www/certbot;", "root /etc;"),
    ],
)
def test_invalid_edit_leaves_previous_config(client, change):
    create_site(client)
    url = "/api/projects/my-app/nginx"
    original = client.get(url).json()["content"]
    result = client.put(url, json={"content": change(original)})
    assert result.status_code == 422, result.text
    assert client.get(url).json()["content"] == original
    assert load_site_config("my-app", get_settings()) == {}


def test_helper_failure_does_not_save_override(client, monkeypatch):
    create_site(client)
    original = client.get("/api/projects/my-app/nginx").json()["content"]
    settings = get_settings().model_copy(update={"nginx_dir": None})
    monkeypatch.setattr("vps_deployer.core.nginx.helper_available", lambda _: True)

    def fail(*args, **kwargs):
        raise HelperError("nginx test/reload failed; previous site restored")

    monkeypatch.setattr("vps_deployer.core.nginx.require_helper", fail)
    with pytest.raises(NginxError, match="restored"):
        save_nginx_config("my-app", original.replace("32m;", "64m;"), settings)
    assert load_site_config("my-app", settings) == {}


def test_external_ssl_survives_reapply_and_is_visible(client, tmp_env):
    create_site(client)
    files = certificate_files(tmp_env)
    result = client.post("/api/projects/my-app/ssl/external", json=files)
    assert result.status_code == 200, result.text
    assert result.json()["provider"] == "external"
    assert result.json()["ssl"]
    assert client.post("/api/projects/my-app/nginx").status_code == 200
    status = client.get("/api/projects/my-app/nginx").json()
    assert status["certificates"] == [files["certificate"]]
    assert status["certificate_keys"] == [files["certificate_key"]]
    assert "listen 443 ssl;" in status["content"]
    assert (
        client.post(
            "/api/projects/my-app/domains", json={"hostname": "www.example.com"}
        ).status_code
        == 201
    )
    rejected = client.post("/api/projects/my-app/domains", json={"hostname": "other.com"})
    assert rejected.status_code == 422
    assert len(client.get("/api/projects/my-app/domains").json()["domains"]) == 2
    page = client.get("/projects/my-app")
    assert files["certificate_key"] in page.text
    assert "PRIVATE KEY" not in page.text


@pytest.mark.parametrize(
    "kwargs", [{"expired": True}, {"mismatch": True}, {"hosts": ["wrong.com"]}]
)
def test_external_ssl_rejects_bad_certificates(client, tmp_env, kwargs):
    create_site(client)
    before = client.get("/api/projects/my-app/nginx").json()["content"]
    files = certificate_files(tmp_env, **kwargs)
    result = client.post("/api/projects/my-app/ssl/external", json=files)
    assert result.status_code == 422, result.text
    assert client.get("/api/projects/my-app/nginx").json()["content"] == before
    assert not client.get("/api/projects/my-app/ssl").json()["ssl"]
    assert load_site_config("my-app", get_settings()) == {}


def test_external_ssl_rejects_paths_and_missing_files(client, tmp_env):
    create_site(client)
    for cert in ("/etc/passwd", str(tmp_env / "ssl/my-app/missing.pem")):
        response = client.post(
            "/api/projects/my-app/ssl/external",
            json={
                "certificate": cert,
                "certificate_key": str(tmp_env / "ssl/my-app/origin.key"),
            },
        )
        assert response.status_code == 422


def test_dashboard_save_reset_and_external_forms(client, tmp_env):
    create_site(client)
    content = client.get("/api/projects/my-app/nginx").json()["content"]
    response = client.post(
        "/projects/my-app/nginx",
        data={"content": content.replace("32m;", "96m;").replace("\n", "\r\n")},
    )
    assert "96m;" in response.text
    assert "Custom config" in response.text
    assert "Generated config" in client.post("/projects/my-app/nginx/reset").text
    response = client.post("/projects/my-app/ssl/external", data=certificate_files(tmp_env))
    assert "origin.key" in response.text
    assert "PRIVATE KEY" not in response.text
