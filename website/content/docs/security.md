---
title: Security
summary: Localhost API, a whitelist helper, and no telemetry.
---

- The API binds to `127.0.0.1`.
- Publishing the dashboard on a hostname or the VPS IP is opt-in through nginx and requires a password.
- The FastAPI process does not run as root.
- Privileged work goes through `/usr/local/libexec/vps-deployer-helper` only.
- sudoers allows that helper, not `NOPASSWD: ALL`.
- Webhooks require `X-Hub-Signature-256`.
- Project names, domains, ports, and paths are validated.
- Application paths cannot escape the apps root.
- Secrets are not written to deployment logs.
- The default installation sends no telemetry.
- This website does not store VPS or GitHub credentials.

See the repository [SECURITY.md](https://github.com/edafeoke/vps-deployer/blob/main/SECURITY.md) for the helper whitelist.
