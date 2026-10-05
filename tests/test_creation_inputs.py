import base64
import json

import pytest

from vps_deployer.core.detection import detect_runtime
from vps_deployer.core.environment import parse_environment, project_environment
from vps_deployer.core.projects import get_project
from vps_deployer.core.validation import ValidationError


@pytest.mark.parametrize(
    "deps,expected", [({"next": "1"}, "nextjs"), ({"vite": "1"}, "vite"), ({}, "node")]
)
def test_detect_package(monkeypatch, deps, expected):
    monkeypatch.setattr("vps_deployer.core.detection.create_installation_token", lambda _: "token")

    def github(method, path, token):
        if "/git/trees/" in path:
            assert "feature%2Ftest" in path
            return {"tree": [{"path": "package.json"}]}
        return {"content": base64.b64encode(json.dumps({"dependencies": deps}).encode()).decode()}

    monkeypatch.setattr("vps_deployer.core.detection.call_github", github)
    assert detect_runtime("owner/repo", "feature/test") == expected


def test_environment_literals():
    assert parse_environment('export TOKEN="a=b # c"\nEMPTY=\nX=$(literal)') == {
        "TOKEN": "a=b # c",
        "EMPTY": "",
        "X": "$(literal)",
    }
    for text in ("INVALID", "PORT=12", "BAD-NAME=x", "A=\x00", 'A="unfinished'):
        with pytest.raises(ValidationError):
            parse_environment(text)


def test_creation_inputs(client):
    response = client.post(
        "/projects",
        data={
            "name": "env-app",
            "repository": "owner/repo",
            "runtime": "flask",
            "environment": "TOKEN=pasted",
            "env_key": "TOKEN",
            "env_value": "literal # value",
        },
        files={"env_file": (".env", b"TOKEN=uploaded\nEMPTY=", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    project = get_project("env-app")
    assert project.runtime == "flask"
    assert project_environment(project) == {"TOKEN": "literal # value", "EMPTY": ""}
    assert "literal" not in client.get("/api/projects/env-app").text


def test_invalid_environment_does_not_create(client):
    response = client.post(
        "/api/projects",
        json={"name": "bad-env", "repository": "o/r", "runtime": "node", "environment": "BAD"},
    )
    assert response.status_code == 422
    assert client.get("/api/projects/bad-env").status_code == 404


def test_environment_reaches_build_and_logs_are_redacted(client, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from sqlmodel import Session

    from vps_deployer.core.config import get_settings
    from vps_deployer.core.engine import _run
    from vps_deployer.db.models import Deployment
    from vps_deployer.db.session import get_engine

    client.post(
        "/api/projects",
        json={
            "name": "build-env",
            "repository": "o/r",
            "runtime": "node",
            "environment": "API_KEY=private-value",
        },
    )
    project = get_project("build-env")
    assert project.id is not None
    with Session(get_engine()) as session:
        deployment = Deployment(project_id=project.id)
        session.add(deployment)
        session.commit()
        session.refresh(deployment)
        deployment_id = deployment.id
        assert deployment_id is not None
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs["env"])
        return SimpleNamespace(stdout="private-value", stderr="", returncode=0)

    monkeypatch.setattr("vps_deployer.core.engine.subprocess.run", run)
    _run(["npm", "run", "build"], tmp_path, deployment_id, get_settings())
    assert seen["API_KEY"] == "private-value"
    assert seen["PORT"] == str(project.port)
    from sqlmodel import select

    from vps_deployer.db.models import DeploymentLog

    with Session(get_engine()) as session:
        assert all(
            "private-value" not in row.message for row in session.exec(select(DeploymentLog))
        )
