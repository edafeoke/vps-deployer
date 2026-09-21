from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_github_pem
from vps_deployer.core.deployments import queue_deployment
from vps_deployer.core.engine import DeployError, _clone_source, execute_deployment
from vps_deployer.core.github import GitHubAuthError, configure_github
from vps_deployer.core.projects import ProjectCreate, create_project, get_project


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(base: Path, repository: str, fail_build: bool = False, extra: str = "") -> str:
    path = base / repository
    path.mkdir(parents=True)
    (path / "index.html").write_text(f"<html><body>ok{extra}</body></html>", encoding="utf-8")
    if fail_build:
        path.joinpath("vps-deployer.json").write_text(
            '{"build_command": ["python3", "-c", "raise SystemExit(1)"]}\n',
            encoding="utf-8",
        )
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "dev@example.com")
    _git(path, "config", "user.name", "Dev")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    return _git(path, "rev-parse", "HEAD")


def test_successful_static_deploy(tmp_env: Path, client: TestClient) -> None:
    sha = _init_repo(tmp_env / "git", "example/my-site")
    create_project(
        ProjectCreate(name="my-site", repository="example/my-site", runtime="static", port=33110)
    )
    queued = client.post("/api/projects/my-site/deploy", json={"commit": sha})
    assert queued.status_code == 202
    deployment_id = queued.json()["deployment"]["id"]
    result = execute_deployment(deployment_id)
    assert result.status == "SUCCESS"
    assert result.commit_sha == sha
    root = tmp_env / "apps" / "my-site"
    assert (root / "current" / "index.html").is_file()
    logs = client.get("/api/projects/my-site/logs")
    assert logs.status_code == 200
    assert any("succeeded" in line.lower() for line in logs.json()["lines"])


def test_failed_build_keeps_previous_release(tmp_env: Path) -> None:
    repo = "example/my-site"
    sha = _init_repo(tmp_env / "git", repo)
    create_project(ProjectCreate(name="my-site", repository=repo, runtime="static", port=33111))
    first = queue_deployment("my-site", sha, "main")
    assert execute_deployment(first.id or 0).status == "SUCCESS"
    current = (tmp_env / "apps" / "my-site" / "current").resolve()

    path = tmp_env / "git" / repo
    path.joinpath("vps-deployer.json").write_text(
        '{"build_command": ["python3", "-c", "raise SystemExit(1)"]}\n',
        encoding="utf-8",
    )
    _git(path, "add", ".")
    _git(path, "commit", "-m", "break build")
    broken = _git(path, "rev-parse", "HEAD")
    second = queue_deployment("my-site", broken, "main")
    result = execute_deployment(second.id or 0)
    assert result.status == "FAILED"
    assert (tmp_env / "apps" / "my-site" / "current").resolve() == current
    assert (current / "index.html").is_file()


def test_failed_first_deploy_does_not_create_current(tmp_env: Path) -> None:
    sha = _init_repo(tmp_env / "git", "example/my-site", fail_build=True)
    create_project(
        ProjectCreate(name="my-site", repository="example/my-site", runtime="static", port=33112)
    )
    queued = queue_deployment("my-site", sha, "main")
    result = execute_deployment(queued.id or 0)
    assert result.status == "FAILED"
    assert not (tmp_env / "apps" / "my-site" / "current").exists()


def test_deploy_unknown_project(client: TestClient) -> None:
    response = client.post("/api/projects/missing-app/deploy")
    assert response.status_code == 404


def test_clone_reports_configured_github_auth_error(tmp_env: Path, monkeypatch) -> None:
    from vps_deployer.core.config import get_settings

    project = create_project(
        ProjectCreate(name="private-site", repository="example/private", runtime="static")
    )
    configure_github(
        app_id="12345",
        private_key=make_github_pem(),
        webhook_secret="supersecret",
    )

    def fail_token(settings):
        raise GitHubAuthError("GitHub API returned HTTP 401")

    monkeypatch.setattr("vps_deployer.core.github.create_installation_token", fail_token)
    with pytest.raises(DeployError, match="GitHub App authentication failed.*HTTP 401"):
        _clone_source(get_project(project.name), get_settings())
