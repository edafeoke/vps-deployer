---
title: Security
summary: Localhost API, a whitelist helper, and no telemetry.
---

- The API binds to `127.0.0.1`.
- Publishing the dashboard on a hostname or the VPS IP is opt-in through nginx and requires a password. Once a password is configured, direct localhost access is protected too; only health, login/logout, static assets, and the authenticated webhook exemption remain public.
- Version 0.7.1 stores dashboard credentials atomically with mode `600` and production service ownership. Updates repair ownership of existing `/etc/vps-deployer/dashboard.json` files. Unreadable or invalid authentication settings return HTTP 503 for the panel (including login) and API; health checks, static assets and independently signed webhooks remain available.

### Password recovery and permissions

Run `sudo vps-deployer dashboard password` on the server to set or reset the password. This invalidates existing browser sessions; refresh an open panel to see the login screen. No service restart is needed.

If authentication settings are unreadable, check the service can read them:

```bash
sudo -u vps-deployer test -r /etc/vps-deployer/dashboard.json
sudo chown vps-deployer:vps-deployer /etc/vps-deployer/dashboard.json
sudo chmod 600 /etc/vps-deployer/dashboard.json
```

If the file is corrupt, restore a valid backup and then reset the password. Do not delete the file to recover access: an installation without a password file remains in its initial unconfigured state. Keep the panel restricted until authentication is verified in a private browser window.

### Host safeguards

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
