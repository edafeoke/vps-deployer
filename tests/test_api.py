from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from vps_deployer.core.config import get_settings
from vps_deployer.db.models import Project
from vps_deployer.db.session import get_engine


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "VPS Deployer"
    assert payload["api"]["host"] == "127.0.0.1"
    assert payload["api"]["port"] == 51999
    assert payload["api"]["healthy"] is True
    assert payload["database"]["healthy"] is True


def test_projects_empty(client: TestClient) -> None:
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json() == {"projects": []}


def test_projects_list(client: TestClient) -> None:
    settings = get_settings()
    with Session(get_engine(settings)) as session:
        session.add(
            Project(
                name="my-next-app",
                repository="example/my-next-app",
                branch="main",
                runtime="nextjs",
                deployment_path="/var/www/apps/my-next-app",
                port=33101,
                service_name="my-next-app",
            )
        )
        session.commit()
    response = client.get("/api/projects")
    assert response.status_code == 200
    rows = response.json()["projects"]
    assert rows[0]["name"] == "my-next-app"
    assert rows[0]["port"] == 33101


def test_doctor_payload(client: TestClient) -> None:
    response = client.get("/api/system/doctor")
    assert response.status_code == 200
    payload = response.json()
    assert "checks" in payload
    assert "summary" in payload
    names = {item["name"] for item in payload["checks"]}
    assert "Operating system" in names
    assert "Database" in names
    db_ok = any(
        item["name"] == "Database" and item["status"] == "PASS" for item in payload["checks"]
    )
    assert db_ok


def test_no_execute_endpoint(client: TestClient) -> None:
    response = client.post("/execute")
    assert response.status_code == 404
