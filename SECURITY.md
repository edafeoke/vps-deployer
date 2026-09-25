# Security

VPS Deployer is infrastructure software. Treat the installer, the privileged helper, and webhook handling as security-critical.

## Product boundary

The public website and your VPS installation are independent.

- The website must not store your VPS credentials.
- Your VPS must not call the website to authorize a deployment.
- After install, deployments work if the website is down.

You do not create a website account to use VPS Deployer.

## Installer

`install.sh` runs as root.

- Use `set -euo pipefail`.
- Prefer HTTPS downloads.
- Reject release tarball members with absolute paths or `..`.
- Unsigned checksums are still a supply-chain residual; inspect the installer before piping it to bash.
- Support `curl -o install.sh` so you can read it first.
- Fail closed on unsupported OS, missing disk, or failed health checks.
- Never run `ufw reset`.
- Never grant `sudo NOPASSWD: ALL` or `NOPASSWD: /bin/bash`.
- Log actions to `/var/log/vps-deployer/installer.log`.

## Process isolation

- `vps-deployer.service` runs as user `vps-deployer`, not root.
- The API listens on `127.0.0.1:5100`.
- The dashboard is the same localhost process. Publishing it on a hostname or the VPS IP is opt-in through nginx and requires a password.
- Dashboard pages must not render private keys, webhook secrets, or environment values.
- There is no `POST /execute` or arbitrary shell endpoint.

## Privileged helper

`/usr/local/libexec/vps-deployer-helper` is the only root path for systemd and nginx operations.

- Fixed whitelist of actions.
- Validate project names, service names, and paths.
- Reject path traversal and shell metacharacters.
- Do not interpolate untrusted input into a shell.

Allowed actions:

- `service-status`
- `nginx-test`, `nginx-reload`, `nginx-site-check`, `nginx-site-install`, `nginx-site-remove`
- `dashboard-site-check`, `dashboard-site-install`, `dashboard-site-remove`
- `ssl-issue`, `ssl-renew`, `ssl-external-check`
- `nginx-site-read` (only the named project's managed site)
- `app-start`, `app-stop`, `app-restart`, `app-status`, `app-enable`, `app-disable`, `app-logs`
- `app-unit-check`, `app-unit-install`, `app-unit-remove`

Application units must be named `vps-deployer-app-<project>.service`. Unit files must run as `vps-deployer`, bind to `127.0.0.1`, use a port in `33000–33999`, and keep `WorkingDirectory` under `/var/www/apps/<project>/`. Shell `ExecStart` lines are rejected. Only the rendered unit keys are accepted. The only allowed `EnvironmentFile` is `-/var/www/apps/<project>/shared/env`. `service-status` may query `vps-deployer.service` or `vps-deployer-app-<project>.service` only.

Nginx site files are allowlisted: listen, server_name, root, proxy_pass, proxy headers, ACME location, TLS paths, and the HTTPS redirect. Unlisted directives (`rewrite`, `fastcgi_pass`, extra `include`) are rejected.

The `vps-deployer` user may run only `/usr/local/libexec/vps-deployer-helper` via `/etc/sudoers.d/vps-deployer`. That snippet is not `NOPASSWD: ALL`.

The platform service must be allowed to execute that setuid `sudo` path, so its unit
does not set `NoNewPrivileges`. Application units do set `NoNewPrivileges=true` and
cannot invoke the helper.

Nginx site files must be named `vps-deployer-<project>.conf`. They may listen on ports 80 and 443, use `server_name` values that pass domain validation, `proxy_pass` only to `http://127.0.0.1:33000-33999`, and `root` only under `/var/www/apps/<project>/` or `/var/www/certbot`. The optional dashboard site is `vps-deployer.conf` and may `proxy_pass` only to `http://127.0.0.1:5100`. TLS files must be `/etc/letsencrypt/live/<hostname>/fullchain.pem` and `privkey.pem`. `include`, `alias`, and shell metacharacters are rejected.

`ssl-issue` accepts only a validated email and hostnames. It runs `certbot certonly --webroot` with a fixed argv list. Private keys stay on disk under `/etc/letsencrypt/` and are never written to logs or SQLite.

External TLS paths are also allowed under `/etc/ssl/vps-deployer/<project>/`, with simple `.pem`, `.crt`, or `.key` filenames. Activation checks root ownership, no symlinks, no group/other writes, private key mode 600/400, validity dates, hostname coverage, and matching public keys. The API/dashboard only receive paths. No Cloudflare API token is required. This validation does not establish public CA trust.

Project Nginx edits may tune request sizes and proxy timeouts. The API preserves routing/TLS declarations and the helper independently enforces its directive allowlist. Failed production test/reload restores the old site. Local development validates config without invoking Nginx.

## Secrets

Store secrets in `/etc/vps-deployer/` with mode `600` or `640` for the `vps-deployer` group. `config.env` is `640` so the installing admin can run the CLI. GitHub App keys stay `600`.

Never store GitHub private keys, webhook secrets, or tokens in:

- Git
- Frontend code
- Public config
- Deployment logs
- Support bundles

CLI `env list` (later) must mask values by default.

## Input validation

Project names must match `^[a-z][a-z0-9-]{1,62}$`.

Reject:

- `../` and absolute path injection
- Shell metacharacters in names and service names
- Application paths outside `/var/www/apps/`

## Webhooks

Verify `X-Hub-Signature-256` with HMAC SHA256. Reject missing or invalid signatures, unknown repositories, and unsupported branches. Webhook payloads must not supply commands. The webhook handler returns quickly and records a `QUEUED` deployment. The local worker processes that queue.

GitHub App private keys and webhook secrets live in the config directory (`/etc/vps-deployer/` in production, `./.local/config/` in development) with mode `600`. They are not stored in SQLite or logs.

## Firewall

Expected public ports: 22, 80, 443.

Diagnostics only in this phase. Future firewall changes must show the intended rules, keep SSH open, and preserve existing UFW rules.

## Privacy

No telemetry by default. Your source code, credentials, and deployment history stay on your VPS.

If telemetry is ever added, it must be optional, disabled by default, documented, and configurable.

## Support bundles (later)

`vps-deployer support bundle` must exclude passwords, private keys, tokens, webhook secrets, and environment values.
