from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from vps_deployer.core.deployments import queue_deployment
from vps_deployer.core.engine import execute_deployment
from vps_deployer.core.projects import ProjectCreate, create_project


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(base: Path, repository: str, body: str = "one") -> str:
    path = base / repository
    path.mkdir(parents=True)
    (path / "index.html").write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "dev@example.com")
    _git(path, "config", "user.name", "Dev")
    _git(path, "add", ".")
    _git(path, "commit", "-m", body)
    return _git(path, "rev-parse", "HEAD")


def test_rollback_previous_static_release(tmp_env: Path, client: TestClient) -> None:
    repo = "example/my-site"
    first_sha = _init_repo(tmp_env / "git", repo, "one")
    create_project(ProjectCreate(name="my-site", repository=repo, runtime="static", port=33140))
    first = queue_deployment("my-site", first_sha, "main")
    assert execute_deployment(first.id or 0).status == "SUCCESS"
    first_current = (tmp_env / "apps" / "my-site" / "current").resolve()

    path = tmp_env / "git" / repo
    path.joinpath("index.html").write_text("<html><body>two</body></html>", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "two")
    second_sha = _git(path, "rev-parse", "HEAD")
    second = queue_deployment("my-site", second_sha, "main")
    assert execute_deployment(second.id or 0).status == "SUCCESS"
    assert "two" in (tmp_env / "apps" / "my-site" / "current" / "index.html").read_text(
        encoding="utf-8"
    )

    response = client.post("/api/projects/my-site/rollback")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ROLLED_BACK"
    current = (tmp_env / "apps" / "my-site" / "current").resolve()
    assert current == first_current
    assert "one" in (current / "index.html").read_text(encoding="utf-8")
    assert (tmp_env / "apps" / "my-site" / "releases").is_dir()
    assert len(list((tmp_env / "apps" / "my-site" / "releases").iterdir())) >= 2


def test_rollback_to_specific_deployment(tmp_env: Path, client: TestClient) -> None:
    repo = "example/my-site"
    first_sha = _init_repo(tmp_env / "git", repo, "one")
    create_project(ProjectCreate(name="my-site", repository=repo, runtime="static", port=33141))
    first = queue_deployment("my-site", first_sha, "main")
    assert execute_deployment(first.id or 0).status == "SUCCESS"
    path = tmp_env / "git" / repo
    path.joinpath("index.html").write_text("<html><body>two</body></html>", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "two")
    second = queue_deployment("my-site", _git(path, "rev-parse", "HEAD"), "main")
    assert execute_deployment(second.id or 0).status == "SUCCESS"
    response = client.post("/api/projects/my-site/rollback", json={"deployment_id": first.id})
    assert response.status_code == 200, response.text
    assert "one" in (tmp_env / "apps" / "my-site" / "current" / "index.html").read_text(
        encoding="utf-8"
    )


def test_rollback_requires_previous_release(tmp_env: Path, client: TestClient) -> None:
    sha = _init_repo(tmp_env / "git", "example/my-site")
    create_project(
        ProjectCreate(name="my-site", repository="example/my-site", runtime="static", port=33142)
    )
    queued = queue_deployment("my-site", sha, "main")
    assert execute_deployment(queued.id or 0).status == "SUCCESS"
    response = client.post("/api/projects/my-site/rollback")
    assert response.status_code == 409
    assert client.post("/api/projects/missing-app/rollback").status_code == 404
    missing_id = client.post("/api/projects/my-site/rollback", json={"deployment_id": 9999})
    assert missing_id.status_code == 404
