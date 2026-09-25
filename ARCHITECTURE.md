# Architecture

Website handover is a queued deployment with project-scoped `pending_handover` intent, tied to its deployment ID and the source config revision. After build/runtime health checks, `core/handover.py` invokes the root-owned host helper to update the existing Nginx file, import its TLS pair, reload and stop selected old services. The project records `host_config_id`; subsequent deploys preserve that file and its custom settings. Domains move into the project only after cutover. Config/service backups support recovery; application data and environment migration remain explicit operator preparation.

VPS Deployer is a self-hosted deployment platform that you install directly on your VPS. After installation, that VPS is the deployment platform. Applications you deploy run on the same machine.

There is no central control plane. The public website does not manage your VPS, store your credentials, or authorize deployments.

```
PUBLIC WEBSITE
      |
      | installer, docs, releases
      ↓
 YOUR VPS
      |
 VPS DEPLOYER INSTALLATION
      |
 YOUR APPLICATIONS
```

## Two independent systems

### Product website

Operated by the product owner at `https://vps-deployer.onebitstack.com`.

Responsibilities:

- Product landing page
- Features and pricing
- Documentation
- Installer distribution (`/install.sh`)
- Releases and changelog
- CLI and API documentation

The website must not:

- Register or list customer VPS instances
- Store SSH or server credentials
- Queue or run customer deployments
- Require an account to install or use VPS Deployer

A VPS Deployer installation must keep working if the website is unavailable. The only operations that naturally need the internet are GitHub access, Let's Encrypt, DNS, and downloading updates.

Public routes:

| Path | Purpose |
| --- | --- |
| `/` | Home |
| `/features` | Features |
| `/pricing` | Pricing |
| `/docs` | Documentation index |
| `/docs/getting-started` | First-run guide |
| `/docs/requirements` | OS and hardware |
| `/docs/installation` | Installer |
| `/docs/first-project` | First application |
| `/docs/github` | GitHub App |
| `/docs/projects` | Project management |
| `/docs/deployments` | Deployments |
| `/docs/domains` | Domains and DNS |
| `/docs/ssl` | HTTPS |
| `/docs/nginx` | Reverse proxy |
| `/docs/environment-variables` | Project env |
| `/docs/rollback` | Rollbacks |
| `/docs/logs` | Logs |
| `/docs/troubleshooting` | Troubleshooting |
| `/docs/security` | Security |
| `/docs/cli` | CLI reference |
| `/docs/api` | API reference |
| `/docs/configuration` | Configuration |
| `/docs/updating` | Updates |
| `/docs/uninstall` | Uninstall |
| `/releases` | Releases |
| `/changelog` | Changelog |
| `/install.sh` | Current installer |

`VPS_DEPLOYER_SITE_URL` is configuration. The VPS runtime uses it only to print documentation and update URLs. It is never required for deploy, rollback, logs, or project management.

### VPS installation

Installed on your VPS, typically under `/opt/vps-deployer`.

Contains:

- FastAPI API bound to `127.0.0.1:5100`
- Local CLI (`vps-deployer`)
- Local SQLite database
- Restricted privileged helper
- systemd service
- Configuration, logs, deployment engine, GitHub webhooks, nginx site files, and Let's Encrypt certificates

Each installation is independent. It manages applications on that VPS only.

## Filesystem layout

### VPS Deployer

```
/opt/vps-deployer/
    app/            # Installed Python application
    bin/            # Wrapper scripts
    releases/       # Platform release artifacts
    scripts/        # Maintenance scripts

/etc/vps-deployer/   # root:vps-deployer, mode 770
    config.env      # Environment / secrets (mode 640)
    config.json     # Non-secret settings
    projects/       # Per-project files (later)

/var/lib/vps-deployer/
    vps-deployer.db

/var/log/vps-deployer/
    installer.log
    api.log
    system.log
    projects/

/usr/local/bin/vps-deployer
/usr/local/libexec/vps-deployer-helper
/etc/sudoers.d/vps-deployer
/etc/systemd/system/vps-deployer.service
/etc/systemd/system/vps-deployer-app-<project>.service
/etc/nginx/sites-available/vps-deployer-<project>.conf
/etc/nginx/sites-enabled/vps-deployer-<project>.conf
/var/www/certbot/
/etc/letsencrypt/live/<hostname>/
```

### Your applications

```
/var/www/apps/<project>/
    current -> releases/<release-id>
    releases/
    shared/
    logs/
```

Application repositories must never live inside `/opt/vps-deployer/app/`.

## Service architecture

```
Internet
    ↓
Nginx :80 / :443          (public traffic for your apps)
    ↓
127.0.0.1:<app-port>      (application systemd unit)

CLI / local dashboard (`/`, `/projects`, `/doctor`)
    ↓
127.0.0.1:5100            (vps-deployer.service, user vps-deployer)
    ↓
SQLite + privileged helper
```

The FastAPI process does not run as root. Privileged operations (systemd, nginx, SSL) go through `/usr/local/libexec/vps-deployer-helper`, which allows a fixed whitelist of actions and validates every argument.

The API is not exposed on the public internet by default.

## Local dashboard

The same FastAPI process serves an HTML console on localhost:

| Path | Purpose |
| --- | --- |
| `/` | This VPS overview |
| `/projects` | Add and list projects |
| `/projects/<name>` | Deployments, domains, HTTPS, logs, start/stop/rollback |
| `/doctor` | Local health checks |

`vps-deployer dashboard` prints `http://127.0.0.1:5100/` by default. `vps-deployer dashboard enable --host panel.example.com` publishes the same console through nginx on port 80/443. Public requests require a password. The API process still binds to `127.0.0.1:5100`. An SSH tunnel remains optional. The pages do not list other VPS instances or send data to the public website. GitHub private keys and webhook secrets are never rendered.

## System user

The installer creates user and group `vps-deployer`.

That user owns `/opt/vps-deployer`, `/var/lib/vps-deployer`, and `/var/log/vps-deployer` where appropriate. It does not receive `NOPASSWD: ALL` or an unrestricted root shell.

## Deployment lifecycle

Later phases implement this flow. The data model already records it.

```
GitHub / CLI / API
    ↓
Validate project
    ↓
Resolve commit
    ↓
Create deployment (QUEUED)
    ↓
Create release directory
    ↓
Fetch repository and checkout
    ↓
Install, optional typecheck, tests, build
    ↓
Start candidate on localhost
    ↓
Health check
    ↓
Switch current symlink
    ↓
Reload nginx if needed
    ↓
Final health check
    ↓
SUCCESS
```

A deployment is successful only when the new release is fetched, built, started, listening, and healthy. A failed candidate must not replace a working `current` release.

Concurrency: one active deployment per project. Additional webhook or CLI requests for the same project create more `QUEUED` records (FIFO). The worker will process one `RUNNING` deployment per project.

## GitHub App

Credentials stay on your VPS:

- `{config_dir}/github-app.pem`
- `{config_dir}/github-webhook-secret`
- `{config_dir}/github.json` (app ID and installation ID only)

The dashboard's GitHub App Manifest handshake derives the webhook and callback URLs
from the persisted public dashboard URL. It stores a short-lived one-time state file,
exchanges GitHub's callback code server-side, writes the generated credentials with
mode `600`, and then redirects to GitHub's repository installation screen. Manual
credential entry remains available.

Webhook flow:

```
GitHub
    ↓
POST /api/github/webhook
    ↓
Verify X-Hub-Signature-256
    ↓
Match repository and branch to a local project
    ↓
Insert deployment QUEUED
    ↓
Return immediately
```

The webhook does not build or restart applications. A local worker consumes `QUEUED` deployments.

## Deployment engine

The API and webhook only enqueue work. A background worker on the VPS:

1. Fetches the repository into a new release directory
2. Installs dependencies and builds
3. Starts a candidate on `127.0.0.1:<port>` when the runtime needs a process
4. Health-checks the candidate
5. Switches `current` only after the candidate is healthy
6. Marks `SUCCESS` or `FAILED`

If the new release fails, `current` stays on the previous successful release. Additional deployments for the same project stay `QUEUED` until that project has no `RUNNING` deployment (FIFO).

Application files live under the configured apps root (`/var/www/apps` in production, `./.local/apps` in local development).

## Rollback lifecycle

```
vps-deployer rollback <project>
    ↓
Find previous successful release
    ↓
Switch current
    ↓
Restart / reload
    ↓
Health check
    ↓
Record rollback
```

The failed or replaced release stays on disk until retention cleanup. The active release is never deleted.

`vps-deployer rollback <project>` restores the previous successful release (or `--to <deployment-id>`). It refuses to run while a deployment is `RUNNING`, records a `ROLLED_BACK` deployment, and puts `current` back if the restored release is unhealthy.

Default retention: 5 successful releases.

## Installer lifecycle

```
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash
    ↓
Detect OS, arch, CPU, RAM, disk, network, sudo
    ↓
Reject unsupported systems
    ↓
Install dependencies
    ↓
Create user and directories
    ↓
Install or update application
    ↓
Preserve existing config and database
    ↓
Install CLI, helper, systemd unit
    ↓
Start and health-check
```

The installer is idempotent. A second run must not delete `/var/www/apps`, `/etc/nginx`, application systemd units, or the SQLite database. If the new platform files fail health checks, the installer restores the previous platform files. Applications are never rolled back.

Sources, in order:

1. `--source <path>` for local development
2. `--version X.Y.Z` from the product website releases
3. Documented fallback until the website release pipeline exists

## Update lifecycle

`vps-deployer update`:

1. Detect the current version
2. Resolve `--version`, or `GET {site_url}/releases/latest.txt`
3. Download `{site_url}/install.sh` over HTTPS
4. Re-run the installer with `--version` or `--source`
5. The installer preserves configuration, the database, and your applications
6. Run migrations
7. Restart `vps-deployer.service`
8. Health-check; roll back the platform update if startup fails

`--force` re-runs the installer when the installed version already matches. The CLI does not download the release tarball or restart application units.

Updating VPS Deployer must not restart or replace your deployed applications.

## Security model

- Local API binds to `127.0.0.1`
- Public dashboard access is nginx plus a password; it is opt-in
- No arbitrary command execution endpoint
- Webhook signatures are required
- Secrets live in `/etc/vps-deployer/` with restrictive permissions
- Secrets are never written to deployment logs
- Project names, domains, ports, and paths are validated
- Application paths cannot escape `/var/www/apps/`
- The privileged helper validates actions and arguments
- Firewall changes never run `ufw reset` and never lock out SSH
- Default installation sends no telemetry

See [SECURITY.md](SECURITY.md).

## Local development vs production

| | Local development | Production VPS |
| --- | --- | --- |
| Config | `./.local/` | `/etc/vps-deployer/` |
| Database | `./.local/vps-deployer.db` | `/var/lib/vps-deployer/vps-deployer.db` |
| API bind | `127.0.0.1:5100` | `127.0.0.1:5100` |
| Process user | current user | `vps-deployer` |
| systemd / nginx | optional; doctor reports WARN | required |

`vps-deployer doctor` must not crash on macOS or other unsupported development machines. Missing systemd or nginx is WARN or FAIL with guidance.

## Application services

Process runtimes (`nextjs`, `node`, `fastapi`, `flask`, `laravel`, `php`) run as `vps-deployer-app-<project>.service` units. The API process does not start them as root. It writes a validated unit and calls the privileged helper:

```
app-unit-install / app-start / app-stop / app-restart / app-status / app-logs / app-unit-remove
```

Units bind to `127.0.0.1` and a reserved port in `33000–33999`. Static and Vite projects have no process unit.

Local development uses a process runtime (pid file under the project `shared/` directory) when systemd or the helper is absent. `VPS_DEPLOYER_RUNTIME=process|systemd|auto` selects the provider.

## Domains and nginx

The host-wide Nginx inventory/editor and Services & processes menus also discover applications outside the deployment database. Fixed helper actions execute `/usr/bin/python3 -I /usr/local/libexec/vps-deployer-admin.py`, a root-owned standalone copy installed alongside the shell helper. JSON requests never contain executable shell commands. Website edits retain backups under `/var/backups/vps-deployer/nginx`, serialize against project installs and validate the active Nginx configuration before reload.

In-place imports live in `/etc/vps-deployer/imported-apps.json`. They associate an application name with its existing Nginx config and optional systemd unit; they do not create deployment records, move files or stop processes. Git-based deployments remain separate projects. Service/config associations also use discovered TCP/Unix listeners and named upstream groups. Process details intentionally omit arguments/environment values.

Domains are stored on this VPS and written to `vps-deployer-<project>.conf` site files. HTTP (`listen 80`) proxies process apps to `127.0.0.1:<port>` or serves static files from `/var/www/apps/<project>/current`. Optional `www` is an extra `server_name`, not a separate project.

The helper installs, tests (`nginx -t`), and reloads nginx. A failed `nginx -t` rolls back the new site file and leaves other sites untouched.

## HTTPS

`vps-deployer ssl enable` issues a Let's Encrypt certificate through the helper (`certbot certonly --webroot`) and rewrites the site with `listen 443 ssl`. Port 80 keeps `/.well-known/acme-challenge/` and redirects other HTTP traffic to HTTPS.

Let's Encrypt certificates live in `/etc/letsencrypt/live/<hostname>/`. External certificates, including Cloudflare Origin CA, use root-owned files under `/etc/ssl/vps-deployer/<project>/`. The helper checks validity, hostname coverage, and key matching. Local development writes short-lived self-signed certificates under the configured SSL directory. Private keys are never stored in SQLite or logs.

The dashboard and CLI expose installed project Nginx config and paths. Saved custom config and external certificate paths live in `/etc/vps-deployer/sites/<project>.json`; deployments preserve this state. Custom config must be reset before domain/SSL changes. Production project-site installs serialize with a lock and restore prior files/symlinks after test or reload failure.

## Runtime abstraction

Deployed applications run through a runtime provider. The production implementation is systemd. The interface is shaped so a Docker provider can be added later without rewriting project or deployment records. Docker is not implemented in this phase.

## Privacy

The default installation does not send telemetry. Your project source, credentials, and deployment history stay on your VPS.

## Versioning

Semantic versioning: `MAJOR.MINOR.PATCH`.

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash -s -- --version 1.2.0
```
