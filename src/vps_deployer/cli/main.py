from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vps_deployer.cli.client import ApiRequestError, ApiUnavailableError, api_get, api_request
from vps_deployer.core.config import get_settings
from vps_deployer.core.doctor import CheckResult, doctor_payload, run_doctor
from vps_deployer.core.github import (
    GitHubAuthError,
    GitHubNotConfiguredError,
    configure_github,
    github_status,
    list_accessible_repositories,
)
from vps_deployer.core.version import get_version

app = typer.Typer(
    name="vps-deployer",
    help="Administer this VPS Deployer installation.",
    no_args_is_help=True,
)
project_app = typer.Typer(help="Manage projects on this VPS.")
github_app = typer.Typer(help="Configure the GitHub App for this VPS.")
app.add_typer(project_app, name="project")
app.add_typer(github_app, name="github")

console = Console()
error_console = Console(stderr=True)

STATUS_GLYPH = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}


@app.command()
def version() -> None:
    """Print the VPS Deployer version."""
    console.print(get_version())


@app.command()
def status() -> None:
    """Show API and database status for this installation."""
    try:
        payload = api_get("/api/status")
    except ApiUnavailableError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"VPS Deployer {payload.get('version', get_version())}")
    api = payload.get("api", {})
    database = payload.get("database", {})
    if isinstance(api, dict):
        console.print(f"API: {api.get('host')}:{api.get('port')} healthy={api.get('healthy')}")
    if isinstance(database, dict):
        console.print(f"Database: healthy={database.get('healthy')} path={database.get('path')}")


@app.command()
def doctor() -> None:
    """Run local health checks. Does not require the API."""
    settings = get_settings()
    checks = run_doctor(settings)
    payload = doctor_payload(settings)
    console.print("VPS Deployer doctor")
    console.print()
    for check in checks:
        _print_check(check)
    summary = payload["summary"]
    assert isinstance(summary, dict)
    console.print()
    console.print(f"PASS {summary['pass']}   WARN {summary['warn']}   FAIL {summary['fail']}")
    if not payload["ok"]:
        raise typer.Exit(code=1)


@app.command()
def projects() -> None:
    """List projects on this VPS."""
    _print_projects()


@project_app.command("list")
def project_list() -> None:
    """List projects on this VPS."""
    _print_projects()


@project_app.command("add")
def project_add(
    name: str = typer.Argument(..., help="Project name, for example my-next-app"),
    repository: str = typer.Option(..., "--repository", "-r", help="GitHub owner/name"),
    branch: str = typer.Option("main", "--branch", "-b"),
    runtime: str = typer.Option("nextjs", "--runtime"),
    port: int | None = typer.Option(None, "--port", help="Localhost port in 33000-33999"),
    domain: str | None = typer.Option(None, "--domain"),
) -> None:
    """Add a project on this VPS. Does not deploy it."""
    body: dict[str, object] = {
        "name": name,
        "repository": repository,
        "branch": branch,
        "runtime": runtime,
    }
    if port is not None:
        body["port"] = port
    if domain is not None:
        body["domain"] = domain
    payload = _api("POST", "/api/projects", body)
    console.print(f"Created project {payload.get('name')}")
    console.print(f"Repository: {payload.get('repository')}")
    console.print(f"Branch: {payload.get('branch')}")
    console.print(f"Runtime: {payload.get('runtime')}")
    console.print(f"Port: {payload.get('port')}")
    console.print(f"Path: {payload.get('deployment_path')}")


@project_app.command("show")
def project_show(name: str) -> None:
    """Show one project on this VPS."""
    payload = _api("GET", f"/api/projects/{name}")
    for key in (
        "name",
        "repository",
        "branch",
        "runtime",
        "port",
        "domain",
        "service_name",
        "deployment_path",
        "enabled",
    ):
        console.print(f"{key}: {payload.get(key)}")


@project_app.command("remove")
def project_remove(
    name: str,
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation"),
) -> None:
    """Remove a project record. Application files are kept."""
    if not yes and not typer.confirm(f"Remove project {name} from this VPS?"):
        raise typer.Abort()
    payload = _api("DELETE", f"/api/projects/{name}")
    console.print(f"Removed project {payload.get('name', name)}")
    console.print("Application files were not deleted.")


@github_app.command("status")
def github_status_cmd() -> None:
    """Show GitHub App configuration for this VPS."""
    payload = github_status(get_settings(), probe=False)
    console.print(f"configured: {payload.get('configured')}")
    console.print(f"app_id: {payload.get('app_id')}")
    console.print(f"installation_id: {payload.get('installation_id')}")
    console.print(f"webhook_path: {payload.get('webhook_path')}")
    if payload.get("error"):
        console.print(f"error: {payload.get('error')}")
        raise typer.Exit(code=1)


@github_app.command("configure")
def github_configure_cmd(
    app_id: str = typer.Option(..., "--app-id", help="GitHub App ID"),
    key_file: Path = typer.Option(..., "--key-file", help="Path to the GitHub App private key PEM"),
    webhook_secret: str = typer.Option(
        ...,
        "--webhook-secret",
        help="Webhook secret. Do not commit this value.",
    ),
    installation_id: str | None = typer.Option(None, "--installation-id"),
) -> None:
    """Store GitHub App credentials on this VPS. Secrets are written with mode 600."""
    if not key_file.is_file():
        error_console.print(f"Private key file not found: {key_file}")
        raise typer.Exit(code=1)
    try:
        configure_github(
            app_id=app_id,
            private_key=key_file.read_text(encoding="utf-8"),
            webhook_secret=webhook_secret,
            installation_id=installation_id,
            settings=get_settings(),
        )
    except ValueError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print("GitHub App configured.")
    console.print("Private key and webhook secret were stored with mode 600.")
    console.print("Next: vps-deployer github repos")


@github_app.command("repos")
def github_repos_cmd() -> None:
    """List repositories the GitHub App can access."""
    try:
        repositories = list_accessible_repositories(get_settings())
    except GitHubNotConfiguredError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    except GitHubAuthError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if not repositories:
        console.print("No repositories available to this GitHub App installation.")
        return
    table = Table(title="GitHub repositories")
    table.add_column("Repository")
    table.add_column("Default branch")
    for row in repositories:
        table.add_row(row["repository"], row["default_branch"])
    console.print(table)


def _api(method: str, path: str, json: dict[str, object] | None = None) -> dict[str, object]:
    try:
        return api_request(method, path, json=json)
    except ApiUnavailableError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    except ApiRequestError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc


def _print_projects() -> None:
    try:
        payload = api_get("/api/projects")
    except ApiUnavailableError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    rows = payload.get("projects", [])
    if not isinstance(rows, list) or not rows:
        console.print("No projects yet.")
        return
    table = Table(title="Projects")
    table.add_column("Name")
    table.add_column("Repository")
    table.add_column("Branch")
    table.add_column("Runtime")
    table.add_column("Port")
    table.add_column("Enabled")
    for row in rows:
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(row.get("name", "")),
            str(row.get("repository", "")),
            str(row.get("branch", "")),
            str(row.get("runtime", "")),
            str(row.get("port", "")),
            "yes" if row.get("enabled") else "no",
        )
    console.print(table)


def _print_check(check: CheckResult) -> None:
    glyph = STATUS_GLYPH[check.status]
    console.print(f"{glyph} {check.name}")
    if check.message:
        console.print(f"  {check.message}")


def run() -> None:
    app()


if __name__ == "__main__":
    sys.exit(run())
