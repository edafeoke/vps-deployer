# Architecture

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

Planned public routes (website phase):

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
- Configuration, logs, and later: deployment engine, GitHub webhooks, nginx/SSL managers

Each installation is independent. It manages applications on that VPS only.

## Filesystem layout

### VPS Deployer

```
/opt/vps-deployer/
    app/            # Installed Python application
    bin/            # Wrapper scripts
    releases/       # Platform release artifacts
    scripts/        # Maintenance scripts

/etc/vps-deployer/
    config.env      # Environment / secrets (mode 600)
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
/etc/systemd/system/vps-deployer.service
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

CLI / local dashboard
    ↓
127.0.0.1:5100            (vps-deployer.service, user vps-deployer)
    ↓
SQLite + privileged helper
```

The FastAPI process does not run as root. Privileged operations (systemd, nginx, SSL) go through `/usr/local/libexec/vps-deployer-helper`, which allows a fixed whitelist of actions and validates every argument.

The API is not exposed on the public internet by default.

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

The webhook does not build or restart applications. That is the deployment engine phase.

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

The failed release stays on disk until retention cleanup. The active release is never deleted.

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

The installer is idempotent. A second run must not delete `/var/www/apps`, `/etc/nginx`, application systemd units, or the SQLite database.

Sources, in order:

1. `--source <path>` for local development
2. `--version X.Y.Z` from the product website releases
3. Documented fallback until the website release pipeline exists

## Update lifecycle

`vps-deployer update` (later phase):

1. Detect current version
2. Download and verify the new release
3. Install the new platform files
4. Preserve configuration, database, and your applications
5. Run migrations
6. Restart `vps-deployer.service`
7. Health-check; roll back the platform update if startup fails

Updating VPS Deployer must not restart or replace your deployed applications.

## Security model

- Local API binds to `127.0.0.1`
- No arbitrary command execution endpoint
- Webhook signatures will be required (later)
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

## Runtime abstraction

Deployed applications will run through a runtime provider. The first implementation is systemd. The interface is shaped so a Docker provider can be added later without rewriting project or deployment records. Docker is not implemented in this phase.

## Privacy

The default installation does not send telemetry. Your project source, credentials, and deployment history stay on your VPS.

## Versioning

Semantic versioning: `MAJOR.MINOR.PATCH`.

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash -s -- --version 1.2.0
```
