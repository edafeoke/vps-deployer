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


def test_hash_values_and_comments():
    assert parse_environment("""# Ignored comment
#DISABLED=unused
COLOR=#ffffff
QUOTED="#secret" # trailing comment
SINGLE='#also-secret'
INLINE=hello # comment
""") == {"COLOR": "#ffffff", "QUOTED": "#secret", "SINGLE": "#also-secret", "INLINE": "hello"}


def test_edit_environment_preserves_and_removes(client):
    client.post(
        "/api/projects",
        json={
            "name": "edit-env",
            "repository": "o/r",
            "runtime": "node",
            "environment": "KEEP=original\nCHANGE=old\nREMOVE=old",
        },
    )
    response = client.post(
        "/projects/edit-env/environment",
        data={
            "environment": "CHANGE=#new",
            "remove": "REMOVE",
            "env_key": "ADDED",
            "env_value": "#field",
        },
        files={"env_file": (".env", b"UPLOAD=#uploaded\n#COMMENT=ignored", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "environment_saved" in response.headers["location"]
    assert project_environment(get_project("edit-env")) == {
        "KEEP": "original",
        "CHANGE": "#new",
        "ADDED": "#field",
        "UPLOAD": "#uploaded",
    }
    page = client.get("/projects/edit-env")
    assert 'action="/projects/edit-env/environment"' in page.text
    assert "#uploaded" not in page.text
    assert 'value="UPLOAD"' in page.text
    invalid = client.patch(
        "/api/projects/edit-env/environment",
        json={"environment": "NEW=valid\nINVALID", "remove": ["KEEP"]},
    )
    assert invalid.status_code == 422
    assert "KEEP" in project_environment(get_project("edit-env"))
    assert "NEW" not in project_environment(get_project("edit-env"))
    conflict = client.patch(
        "/api/projects/edit-env/environment", json={"environment": "KEEP=new", "remove": ["KEEP"]}
    )
    assert conflict.status_code == 422
    updated = client.patch(
        "/api/projects/edit-env/environment",
        json={"environment": "CHANGE=", "remove": ["KEEP", "ADDED", "UPLOAD"]},
    )
    assert updated.status_code == 200
    assert updated.json()["keys"] == ["CHANGE"]
    assert project_environment(get_project("edit-env")) == {"CHANGE": ""}
    client.patch("/api/projects/edit-env/environment", json={"remove": ["CHANGE"]})
    assert project_environment(get_project("edit-env")) == {}


def test_branches_and_repository_selectors(client, monkeypatch):
    monkeypatch.setattr(
        "vps_deployer.api.main.list_repository_branches",
        lambda repo, settings: ["main", "feature/test"],
    )
    response = client.get("/api/github/branches", params={"repository": "o/r"})
    assert response.json() == {"branches": ["main", "feature/test"]}
    page = client.get("/projects").text
    assert '<select name="repository"' in page
    assert '<select name="branch"' in page


def test_github_choice_pagination(monkeypatch):
    from vps_deployer.core.github import list_accessible_repositories, list_repository_branches

    monkeypatch.setattr("vps_deployer.core.github.create_installation_token", lambda _: "token")
    calls = []

    def github(method, path, token):
        calls.append(path)
        first = path.endswith("page=1")
        if "/installation/repositories" in path:
            return {
                "repositories": [
                    {"full_name": f"org/repo-{i}", "default_branch": "dev"}
                    for i in (range(100) if first else [100])
                ]
            }
        return [{"name": f"branch-{i}"} for i in (range(100) if first else [100])]

    monkeypatch.setattr("vps_deployer.core.github.call_github", github)
    assert len(list_accessible_repositories()) == 101
    assert len(list_repository_branches("org/repo")) == 101
    assert len(calls) == 4
    with pytest.raises(ValidationError):
        list_repository_branches("../bad")


def test_environment_form_quotes_are_literal():
    from vps_deployer.core.environment import merge_environment_inputs

    value = 'a" # literal \\ value'
    text = merge_environment_inputs("", keys=["VALUE"], values=[value])
    assert parse_environment(text) == {"VALUE": value}
    assert parse_environment('VALUE="a" # comment with "quotes"') == {"VALUE": "a"}
