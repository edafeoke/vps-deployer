from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import make_github_pem
from vps_deployer.core.github import configure_github


def test_dashboard_overview(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "This VPS" in response.text
    assert "VPS Deployer" in response.text
    assert "No projects on this VPS yet" in response.text


def test_dashboard_static_assets(client: TestClient) -> None:
    css = client.get("/static/dashboard.css")
    assert css.status_code == 200
    assert "--amber" in css.text
    script = client.get("/static/dashboard.js")
    assert script.status_code == 200


def test_dashboard_doctor(client: TestClient) -> None:
    response = client.get("/doctor")
    assert response.status_code == 200
    assert "Operating system" in response.text
    assert "Database" in response.text


def test_dashboard_create_and_show(client: TestClient) -> None:
    created = client.post(
        "/projects",
        data={
            "name": "my-next-app",
            "repository": "example/my-next-app",
            "branch": "main",
            "runtime": "static",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"].startswith("/projects/my-next-app")
    page = client.get("/projects/my-next-app")
    assert page.status_code == 200
    assert "my-next-app" in page.text
    assert "example/my-next-app" in page.text
    assert "BEGIN" not in page.text
    listing = client.get("/projects")
    assert "my-next-app" in listing.text
    overview = client.get("/")
    assert "my-next-app" in overview.text


def test_dashboard_deploy_form(client: TestClient) -> None:
    client.post(
        "/projects",
        data={
            "name": "my-api",
            "repository": "example/my-api",
            "branch": "main",
            "runtime": "static",
        },
    )
    queued = client.post("/projects/my-api/deploy", follow_redirects=False)
    assert queued.status_code == 303
    page = client.get("/projects/my-api")
    assert page.status_code == 200
    assert "QUEUED" in page.text


def test_dashboard_missing_and_invalid(client: TestClient) -> None:
    missing = client.get("/projects/missing-app")
    assert missing.status_code == 404
    assert "missing-app" in missing.text
    invalid = client.get("/projects/Not_Valid")
    assert invalid.status_code == 422


def test_dashboard_hides_github_secrets(client: TestClient, tmp_env) -> None:
    secret = "supersecret-webhook"
    configure_github(
        app_id="12345",
        private_key=make_github_pem(),
        webhook_secret=secret,
        settings=None,
    )
    page = client.get("/")
    assert page.status_code == 200
    assert "configured" in page.text
    assert secret not in page.text
    assert "BEGIN" not in page.text
    assert "PRIVATE KEY" not in page.text
