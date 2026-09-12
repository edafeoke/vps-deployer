from __future__ import annotations

from fastapi.testclient import TestClient

from vps_deployer.core.projects import (
    ProjectConflictError,
    ProjectCreate,
    allocate_port,
    create_project,
    reserved_ports,
)
from vps_deployer.core.validation import ValidationError


def test_create_show_delete_project(client: TestClient) -> None:
    created = client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "my-next-app"
    assert body["repository"] == "example/my-next-app"
    assert body["branch"] == "main"
    assert body["runtime"] == "nextjs"
    assert body["deployment_path"].endswith("/apps/my-next-app")
    assert body["service_name"] == "vps-deployer-app-my-next-app"
    assert 33000 <= body["port"] <= 33999

    shown = client.get("/api/projects/my-next-app")
    assert shown.status_code == 200
    assert shown.json()["port"] == body["port"]

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert listed.json()["projects"][0]["name"] == "my-next-app"

    deleted = client.delete("/api/projects/my-next-app")
    assert deleted.status_code == 200
    assert client.get("/api/projects/my-next-app").status_code == 404
    assert client.get("/api/projects").json() == {"projects": []}


def test_duplicate_project_name(client: TestClient) -> None:
    payload = {"name": "my-api", "repository": "example/my-api"}
    assert client.post("/api/projects", json=payload).status_code == 201
    duplicate = client.post("/api/projects", json=payload)
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_invalid_project_name(client: TestClient) -> None:
    response = client.post(
        "/api/projects",
        json={"name": "../etc", "repository": "example/my-api"},
    )
    assert response.status_code == 422
    assert client.get("/api/projects/NotValid").status_code == 422
    assert client.delete("/api/projects/app;reboot").status_code == 422


def test_unknown_project(client: TestClient) -> None:
    assert client.get("/api/projects/missing-app").status_code == 404
    assert client.delete("/api/projects/missing-app").status_code == 404


def test_requested_port_and_conflict(client: TestClient) -> None:
    first = client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "port": 33101},
    )
    assert first.status_code == 201
    assert first.json()["port"] == 33101
    conflict = client.post(
        "/api/projects",
        json={"name": "my-api", "repository": "example/my-api", "port": 33101},
    )
    assert conflict.status_code == 409


def test_invalid_port_and_runtime(client: TestClient) -> None:
    port = client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "port": 80},
    )
    assert port.status_code == 422
    runtime = client.post(
        "/api/projects",
        json={"name": "my-next-app", "repository": "example/my-next-app", "runtime": "docker"},
    )
    assert runtime.status_code == 422


def test_allocate_port_skips_reserved(tmp_env) -> None:
    create_project(ProjectCreate(name="my-next-app", repository="example/my-next-app", port=33000))
    assert 33000 in reserved_ports()
    assert allocate_port() != 33000


def test_create_project_rejects_bad_repo(tmp_env) -> None:
    try:
        create_project(ProjectCreate(name="my-next-app", repository="/etc/passwd"))
    except ValidationError:
        return
    raise AssertionError("expected ValidationError")


def test_requested_port_in_use_on_localhost(tmp_env) -> None:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 33222))
    sock.listen(1)
    try:
        try:
            allocate_port(33222)
        except ProjectConflictError:
            return
        raise AssertionError("expected ProjectConflictError")
    finally:
        sock.close()
