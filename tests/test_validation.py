from __future__ import annotations

import pytest

from vps_deployer.core.validation import (
    ValidationError,
    validate_app_path,
    validate_branch,
    validate_domain,
    validate_env_name,
    validate_port,
    validate_project_name,
    validate_repository,
    validate_runtime,
    validate_service_name,
)


def test_valid_project_name() -> None:
    assert validate_project_name("my-next-app") == "my-next-app"


@pytest.mark.parametrize(
    "name",
    ["", "A", "MyApp", "1app", "app_name", "../etc", "app;reboot", "app$(id)", "a", "x" * 64],
)
def test_invalid_project_name(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_project_name(name)


def test_service_name_rejects_injection() -> None:
    with pytest.raises(ValidationError):
        validate_service_name("vps-deployer.service; reboot")
    with pytest.raises(ValidationError):
        validate_service_name("../etc/passwd")
    assert validate_service_name("my-next-app") == "my-next-app"


def test_repository_and_branch() -> None:
    assert validate_repository("example/my-next-app") == "example/my-next-app"
    with pytest.raises(ValidationError):
        validate_repository("/etc/passwd")
    with pytest.raises(ValidationError):
        validate_repository("example/foo;rm")
    assert validate_branch("main") == "main"
    with pytest.raises(ValidationError):
        validate_branch("main;echo")


def test_domain_and_port() -> None:
    assert validate_domain("example.com") == "example.com"
    with pytest.raises(ValidationError):
        validate_domain("not a domain")
    assert validate_port(33101) == 33101
    with pytest.raises(ValidationError):
        validate_port(80)


def test_runtime() -> None:
    assert validate_runtime("NextJS") == "nextjs"
    with pytest.raises(ValidationError):
        validate_runtime("docker")


def test_env_name() -> None:
    assert validate_env_name("DATABASE_URL") == "DATABASE_URL"
    with pytest.raises(ValidationError):
        validate_env_name("1BAD")


def test_app_path_traversal() -> None:
    with pytest.raises(ValidationError):
        validate_app_path("../../etc/passwd", "my-next-app")
    with pytest.raises(ValidationError):
        validate_app_path("/etc/passwd", "my-next-app")
    path = validate_app_path("/var/www/apps/my-next-app", "my-next-app")
    assert path.name == "my-next-app"
