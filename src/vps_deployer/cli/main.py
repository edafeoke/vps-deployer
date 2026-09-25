from __future__ import annotations

import sys
import time
from pathlib import Path

import click
import typer
from rich.console import Console
from rich.table import Table

from vps_deployer.cli.client import ApiRequestError, ApiUnavailableError, api_get, api_request
from vps_deployer.core.config import get_settings
from vps_deployer.core.dashboard_access import (
    DashboardAccessError,
    dashboard_public_url,
    detect_public_ipv4,
    disable_dashboard_access,
    enable_dashboard_access,
    enable_dashboard_ssl,
    set_dashboard_password,
)
from vps_deployer.core.doctor import CheckResult, doctor_payload, run_doctor
from vps_deployer.core.domains import DomainConflictError
from vps_deployer.core.github import (
    GitHubAuthError,
    GitHubNotConfiguredError,
    configure_github,
    github_status,
    list_accessible_repositories,
)
from vps_deployer.core.nginx import NginxError
from vps_deployer.core.ssl import SslError
from vps_deployer.core.uninstall import UninstallError, run_uninstall
from vps_deployer.core.update import UpdateError, run_update
from vps_deployer.core.validation import ValidationError
from vps_deployer.core.version import get_version

app = typer.Typer(
    name="vps-deployer",
    help="Administer this VPS Deployer installation.",
    no_args_is_help=True,
)
project_app = typer.Typer(help="Manage projects on this VPS.")
github_app = typer.Typer(help="Configure the GitHub App for this VPS.")
domain_app = typer.Typer(help="Attach domains on this VPS.")
ssl_app = typer.Typer(help="Enable HTTPS on this VPS.")
nginx_app = typer.Typer(help="Inspect and edit project Nginx configuration.")
dashboard_app = typer.Typer(
    help="Open or publish the dashboard for this VPS.",
    invoke_without_command=True,
)
app.add_typer(project_app, name="project")
app.add_typer(github_app, name="github")
app.add_typer(domain_app, name="domain")
app.add_typer(ssl_app, name="ssl")
app.add_typer(nginx_app, name="nginx")
app.add_typer(dashboard_app, name="dashboard")

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


@dashboard_app.callback(invoke_without_command=True)
def dashboard(ctx: typer.Context) -> None:
    """Print the dashboard URL for this VPS."""
    if ctx.invoked_subcommand is not None:
        return
    _print_dashboard_url()


@dashboard_app.command("enable")
def dashboard_enable(
    host: list[str] | None = typer.Option(
        None,
        "--host",
        help="Public hostname, for example panel.example.com",
    ),
    use_ip: bool = typer.Option(False, "--ip", help="Also publish on the VPS public IPv4 address"),
    password: str | None = typer.Option(
        None,
        "--password",
        help="Dashboard password. Generated once if omitted and none is stored.",
    ),
) -> None:
    """Publish the dashboard on a hostname and/or the VPS public IP."""
    hosts = list(host or [])
    if use_ip:
        try:
            hosts.append(detect_public_ipv4())
        except DashboardAccessError as exc:
            error_console.print(str(exc))
            raise typer.Exit(code=1) from exc
    if not hosts:
        error_console.print("Provide --host and/or --ip.")
        raise typer.Exit(code=1)
    try:
        payload = enable_dashboard_access(hosts=hosts, password=password, settings=get_settings())
    except (DashboardAccessError, DomainConflictError, NginxError, ValidationError) as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    url = payload.get("url")
    console.print(f"Public dashboard: {url}")
    published = payload.get("hosts")
    if isinstance(published, list):
        console.print("hosts: " + ", ".join(str(item) for item in published))
    generated = payload.get("password")
    if isinstance(generated, str) and generated:
        console.print(f"Generated password (shown once): {generated}")
    console.print("The API still binds to 127.0.0.1:5100.")


@dashboard_app.command("disable")
def dashboard_disable() -> None:
    """Stop publishing the dashboard on the public hostname or IP."""
    try:
        disable_dashboard_access(get_settings())
    except NginxError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print("Public dashboard disabled.")
    _print_dashboard_url()


@dashboard_app.command("password")
def dashboard_password_cmd(
    password: str | None = typer.Option(None, "--password", help="New dashboard password"),
) -> None:
    """Set or replace the public dashboard password."""
    value = password or typer.prompt(
        "Dashboard password",
        hide_input=True,
        confirmation_prompt=True,
    )
    try:
        set_dashboard_password(value, get_settings())
    except DashboardAccessError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print("Dashboard password updated.")


@dashboard_app.command("ssl")
def dashboard_ssl(
    email: str | None = typer.Option(None, "--email", help="Let's Encrypt notice address"),
) -> None:
    """Issue a certificate for the public dashboard hostname."""
    try:
        payload = enable_dashboard_ssl(email, get_settings())
    except (DashboardAccessError, SslError, NginxError, ValidationError) as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"HTTPS enabled: {payload.get('url')}")
    console.print(f"certificate: {payload.get('certificate')}")


def _print_dashboard_url() -> None:
    settings = get_settings()
    public = dashboard_public_url(settings)
    if public:
        console.print(f"Public dashboard: {public}")
        console.print(f"Local dashboard: {settings.api_base_url}/")
        return
    console.print(f"Local dashboard: {settings.api_base_url}/")
    console.print("This page is only available on this VPS (localhost).")


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
def update(
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation"),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Install this release version from the product website",
    ),
    source: Path | None = typer.Option(
        None,
        "--source",
        help="Install from a local checkout instead of a published release",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-run the installer even when the installed version matches",
    ),
) -> None:
    """Update VPS Deployer on this VPS. Applications are kept."""
    if not yes and not typer.confirm("Update VPS Deployer on this VPS? Applications will be kept."):
        raise typer.Abort()
    try:
        result = run_update(
            version=version,
            source=source,
            force=force,
            site_url=get_settings().site_url,
        )
    except UpdateError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    if result.skipped:
        console.print(result.message)


@app.command()
def uninstall(
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation"),
    purge: bool = typer.Option(
        False,
        "--purge",
        help="Also remove applications, app units, and app nginx sites",
    ),
) -> None:
    """Remove VPS Deployer from this VPS. Applications are kept unless --purge."""
    if purge:
        prompt = "Remove VPS Deployer and all applications on this VPS?"
    else:
        prompt = "Remove VPS Deployer from this VPS? Applications will be kept."
    if not yes and not typer.confirm(prompt):
        raise typer.Abort()
    try:
        result = run_uninstall(purge=purge)
    except UninstallError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for path in result.removed:
        console.print(f"removed {path}")
    if purge:
        console.print("VPS Deployer and applications were removed.")
    else:
        console.print("VPS Deployer was removed. Applications were not deleted.")


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


@app.command()
def deploy(
    name: str,
    commit: str | None = typer.Option(None, "--commit", help="Commit SHA to deploy"),
    wait: bool = typer.Option(False, "--wait", help="Wait until the worker finishes"),
) -> None:
    """Queue a deployment for a project on this VPS."""
    body: dict[str, object] = {}
    if commit:
        body["commit"] = commit
    payload = _api("POST", f"/api/projects/{name}/deploy", body or None)
    deployment = payload.get("deployment")
    deployment_id = deployment.get("id") if isinstance(deployment, dict) else None
    console.print(f"Queued deployment {deployment_id} for {name}")
    if not wait:
        console.print("The worker builds and activates the release asynchronously.")
        return
    for _ in range(180):
        listing = _api("GET", f"/api/projects/{name}/deployments")
        rows = listing.get("deployments")
        if isinstance(rows, list) and rows:
            latest = rows[0]
            if isinstance(latest, dict):
                status = latest.get("status")
                console.print(f"status: {status}")
                if status == "SUCCESS":
                    return
                if status == "FAILED":
                    error_console.print(str(latest.get("error_message") or "Deployment failed"))
                    raise typer.Exit(code=1)
        time.sleep(1)
    error_console.print("Timed out waiting for the deployment worker")
    raise typer.Exit(code=1)


@app.command()
def rollback(
    name: str,
    to: int | None = typer.Option(None, "--to", help="Deployment ID to restore"),
) -> None:
    """Restore the previous successful release on this VPS."""
    body: dict[str, object] = {}
    if to is not None:
        body["deployment_id"] = to
    payload = _api("POST", f"/api/projects/{name}/rollback", body or None)
    deployment = payload.get("deployment")
    deployment_id = deployment.get("id") if isinstance(deployment, dict) else None
    console.print(f"Rolled back {name} to deployment {deployment_id}")
    if isinstance(deployment, dict) and deployment.get("commit_sha"):
        console.print(f"commit: {deployment.get('commit_sha')}")
    console.print(f"status: {payload.get('status')}")


@app.command()
def logs(
    name: str,
    deployment: int | None = typer.Option(None, "--deployment", help="Deployment ID"),
    service: bool = typer.Option(False, "--service", help="Show application process logs"),
) -> None:
    """Show deployment or application service logs for a project."""
    if service:
        path = f"/api/projects/{name}/service/logs"
    else:
        path = f"/api/projects/{name}/logs"
        if deployment is not None:
            path = f"{path}?deployment_id={deployment}"
    payload = _api("GET", path)
    lines = payload.get("lines", [])
    if not isinstance(lines, list) or not lines:
        console.print("No logs yet.")
        return
    for line in lines:
        console.print(str(line))


@app.command()
def start(name: str) -> None:
    """Start the application process or systemd unit on this VPS."""
    payload = _api("POST", f"/api/projects/{name}/start")
    console.print(f"{payload.get('name')}: {payload.get('detail', 'started')}")
    console.print(f"running: {payload.get('running')}")
    console.print(f"service: {payload.get('service_name')}")


@app.command()
def stop(name: str) -> None:
    """Stop the application process or systemd unit on this VPS."""
    payload = _api("POST", f"/api/projects/{name}/stop")
    console.print(f"{payload.get('name')}: {payload.get('detail', 'stopped')}")
    console.print(f"running: {payload.get('running')}")


@app.command()
def restart(name: str) -> None:
    """Restart the application process or systemd unit on this VPS."""
    payload = _api("POST", f"/api/projects/{name}/restart")
    console.print(f"{payload.get('name')}: {payload.get('detail', 'restarted')}")
    console.print(f"running: {payload.get('running')}")


@domain_app.command("list")
def domain_list(name: str) -> None:
    """List domains attached to a project on this VPS."""
    payload = _api("GET", f"/api/projects/{name}/domains")
    rows = payload.get("domains", [])
    if not isinstance(rows, list) or not rows:
        console.print("No domains yet.")
        return
    table = Table(title=f"Domains for {name}")
    table.add_column("Hostname")
    table.add_column("www")
    table.add_column("ssl")
    for row in rows:
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(row.get("hostname", "")),
            "yes" if row.get("www") else "no",
            "yes" if row.get("ssl") else "no",
        )
    console.print(table)


@domain_app.command("add")
def domain_add(
    name: str,
    hostname: str,
    www: bool = typer.Option(False, "--www", help="Also serve www.<hostname>"),
) -> None:
    """Attach a domain to a project and write the nginx site."""
    payload = _api(
        "POST",
        f"/api/projects/{name}/domains",
        {"hostname": hostname, "www": www},
    )
    console.print(f"Attached {payload.get('hostname')} to {name}")
    if payload.get("www"):
        console.print(f"www.{payload.get('hostname')} is also served")
    console.print("Next: vps-deployer ssl enable " + name)


@domain_app.command("remove")
def domain_remove(name: str, hostname: str) -> None:
    """Detach a domain and update the nginx site."""
    _api("DELETE", f"/api/projects/{name}/domains/{hostname}")
    console.print(f"Removed {hostname} from {name}")


@ssl_app.command("enable")
def ssl_enable(
    name: str,
    hostname: str | None = typer.Argument(None, help="Hostname, or all project domains"),
    email: str | None = typer.Option(None, "--email", help="Let's Encrypt notice address"),
) -> None:
    """Issue a certificate and serve the project over HTTPS."""
    body: dict[str, object] = {}
    if hostname:
        body["hostname"] = hostname
    if email:
        body["email"] = email
    payload = _api("POST", f"/api/projects/{name}/ssl", body or None)
    console.print(f"HTTPS enabled for {payload.get('project')}")
    console.print(f"certificate: {payload.get('certificate')}")
    hosts = payload.get("hostnames")
    if isinstance(hosts, list):
        console.print("hostnames: " + ", ".join(str(item) for item in hosts))


@ssl_app.command("status")
def ssl_status_cmd(name: str) -> None:
    """Show HTTPS status for a project on this VPS."""
    payload = _api("GET", f"/api/projects/{name}/ssl")
    console.print(f"project: {payload.get('project')}")
    console.print(f"ssl: {payload.get('ssl')}")
    console.print(f"email: {payload.get('email')}")
    for key in ("provider", "certificate", "certificate_key"):
        console.print(f"{key}: {payload.get(key)}", markup=False)
    rows = payload.get("domains", [])
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                console.print(f"{row.get('hostname')}: ssl={row.get('ssl')} www={row.get('www')}")


@nginx_app.command("show")
def nginx_show(name: str, raw: bool = typer.Option(False, "--raw")) -> None:
    """Show installed Nginx config and app/TLS file locations."""
    payload = _api("GET", f"/api/projects/{name}/nginx")
    if not raw:
        for key in (
            "path",
            "installed",
            "custom",
            "deployment_path",
            "current_path",
            "release_path",
            "roots",
            "upstreams",
            "certificates",
            "certificate_keys",
            "error",
        ):
            console.print(f"{key}: {payload.get(key)}", markup=False)
    # Avoid Rich markup/highlighting/wrapping: --raw can be redirected to a config file.
    typer.echo(str(payload.get("content", "")), nl=False)


@nginx_app.command("edit")
def nginx_edit(name: str) -> None:
    """Edit in $VISUAL/$EDITOR, validate, and apply the project site."""
    payload = _api("GET", f"/api/projects/{name}/nginx")
    edited = click.edit(str(payload.get("content", "")), extension=".conf")
    if edited is None:
        console.print("No changes.")
        return
    _api("PUT", f"/api/projects/{name}/nginx", {"content": edited})
    console.print("Nginx config saved and applied.")


@nginx_app.command("apply")
def nginx_apply(
    name: str,
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False),
) -> None:
    """Validate and apply a config file, preserving it across deployments."""
    _api("PUT", f"/api/projects/{name}/nginx", {"content": file.read_text(encoding="utf-8")})
    console.print("Nginx config saved and applied.")


@nginx_app.command("reset")
def nginx_reset(name: str, yes: bool = typer.Option(False, "--yes")) -> None:
    """Discard custom edits and restore generated config."""
    if not yes and not typer.confirm("Discard custom Nginx edits?"):
        raise typer.Abort()
    _api("DELETE", f"/api/projects/{name}/nginx")
    console.print("Generated Nginx config restored.")


@ssl_app.command("external")
def ssl_external(
    name: str,
    certificate: str = typer.Option(..., "--certificate", help="Certificate path on the VPS"),
    key: str = typer.Option(..., "--key", help="Private key path on the VPS"),
) -> None:
    """Use an existing certificate, including Cloudflare Origin CA."""
    payload = _api(
        "POST",
        f"/api/projects/{name}/ssl/external",
        {"certificate": certificate, "certificate_key": key},
    )
    console.print(f"External HTTPS enabled for {payload.get('project')}")
    console.print(f"certificate: {payload.get('certificate')}", markup=False)
    console.print(f"certificate_key: {payload.get('certificate_key')}", markup=False)


@ssl_app.command("renew")
def ssl_renew() -> None:
    """Renew certificates on this VPS."""
    payload = _api("POST", "/api/ssl/renew")
    console.print(f"renewed: {payload.get('renewed')} mode={payload.get('mode')}")


@github_app.command("status")
def github_status_cmd() -> None:
    """Show GitHub App configuration for this VPS."""
    payload = github_status(get_settings(), probe=False)
    console.print(f"configured: {payload.get('configured')}")
    console.print(f"app_id: {payload.get('app_id')}")
    console.print(f"installation_id: {payload.get('installation_id')}")
    console.print(f"webhook_path: {payload.get('webhook_path')}")
    console.print(f"webhook_url: {payload.get('webhook_url')}")
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
