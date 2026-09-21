from __future__ import annotations

import pytest

from vps_deployer.core.validation import (
    ValidationError,
    validate_app_path,
    validate_branch,
    validate_dashboard_host,
    validate_domain,
    validate_email,
    validate_env_name,
    validate_ipv4,
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


def test_email() -> None:
    assert validate_email("ops@example.com") == "ops@example.com"
    with pytest.raises(ValidationError):
        validate_email("not-an-email")
    with pytest.raises(ValidationError):
        validate_email("ops@example..com")


def test_dashboard_host_and_ipv4() -> None:
    assert validate_ipv4("203.0.113.10") == "203.0.113.10"
    assert validate_dashboard_host("panel.example.com") == "panel.example.com"
    assert validate_dashboard_host("https://panel.example.com/") == "panel.example.com"
    assert validate_dashboard_host("http://panel.example.com") == "panel.example.com"
    assert validate_dashboard_host("203.0.113.10") == "203.0.113.10"
    with pytest.raises(ValidationError):
        validate_ipv4("999.1.1.1")
    with pytest.raises(ValidationError):
        validate_dashboard_host("127.0.0.1")
    with pytest.raises(ValidationError):
        validate_dashboard_host("0.0.0.0")
    with pytest.raises(ValidationError):
        validate_dashboard_host("https://panel.example.com/settings")
    with pytest.raises(ValidationError):
        validate_dashboard_host("https://user@panel.example.com/")


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
