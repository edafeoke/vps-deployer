---
title: Security
summary: Localhost API, a whitelist helper, and no telemetry.
---

- The API binds to `127.0.0.1`.
- Publishing the dashboard on a hostname or the VPS IP is opt-in through nginx and requires a password. Once a password is configured, direct localhost access is protected too; only health, login/logout, static assets, and the authenticated webhook exemption remain public.
- The FastAPI process does not run as root.
- Privileged work goes through `/usr/local/libexec/vps-deployer-helper` only.
- sudoers allows that helper, not `NOPASSWD: ALL`.
- The platform unit permits that restricted sudo path; deployed application units use
  `NoNewPrivileges=true` and cannot invoke it.
- Webhooks require `X-Hub-Signature-256`.
- Project names, domains, ports, and paths are validated.
- Application paths cannot escape the apps root.
- Secrets are not written to deployment logs.
- The default installation sends no telemetry.
- This website does not store VPS or GitHub credentials.

The Nginx and Services menus grant operational control over eligible existing host configs and services, including unmanaged apps. Treat dashboard access as host administration access. The root helper constrains file paths/directives, checks config revisions and Nginx validation, retains backups, protects infrastructure services, and omits process arguments/environment values. Cross-origin host mutations are rejected.

See the repository [SECURITY.md](https://github.com/edafeoke/vps-deployer/blob/main/SECURITY.md) for the helper whitelist.
