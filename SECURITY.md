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
- Support `curl -o install.sh` so you can read it first.
- Fail closed on unsupported OS, missing disk, or failed health checks.
- Never run `ufw reset`.
- Never grant `sudo NOPASSWD: ALL` or `NOPASSWD: /bin/bash`.
- Log actions to `/var/log/vps-deployer/installer.log`.

## Process isolation

- `vps-deployer.service` runs as user `vps-deployer`, not root.
- The API listens on `127.0.0.1:5100`.
- There is no `POST /execute` or arbitrary shell endpoint.

## Privileged helper

`/usr/local/libexec/vps-deployer-helper` is the only root path for systemd and nginx operations.

- Fixed whitelist of actions.
- Validate project names, service names, and paths.
- Reject path traversal and shell metacharacters.
- Do not interpolate untrusted input into a shell.

This phase allows `service-status` and `nginx-test` only.

## Secrets

Store secrets in `/etc/vps-deployer/` with mode `600`.

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

Verify `X-Hub-Signature-256` with HMAC SHA256. Reject missing or invalid signatures, unknown repositories, and unsupported branches. Webhook payloads must not supply commands. The webhook handler returns quickly and records a `QUEUED` deployment. The deploy engine (later) processes that queue.

GitHub App private keys and webhook secrets live in the config directory (`/etc/vps-deployer/` in production, `./.local/config/` in development) with mode `600`. They are not stored in SQLite or logs.

## Firewall

Expected public ports: 22, 80, 443.

Diagnostics only in this phase. Future firewall changes must show the intended rules, keep SSH open, and preserve existing UFW rules.

## Privacy

No telemetry by default. Your source code, credentials, and deployment history stay on your VPS.

If telemetry is ever added, it must be optional, disabled by default, documented, and configurable.

## Support bundles (later)

`vps-deployer support bundle` must exclude passwords, private keys, tokens, webhook secrets, and environment values.
