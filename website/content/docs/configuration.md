---
title: Configuration
summary: Environment and files for this installation.
---

Production config lives in `/etc/vps-deployer/`. Local development uses `./.local/`.

`VPS_DEPLOYER_SITE_URL` (default `https://vps-deployer.centralstackhq.com`) is only used to print documentation and update URLs. Deploy, rollback, logs, and project management do not require this website.

Useful variables:

| Variable | Purpose |
| --- | --- |
| `VPS_DEPLOYER_API_HOST` | Bind host (`127.0.0.1`) |
| `VPS_DEPLOYER_API_PORT` | Bind port (`5100`) |
| `VPS_DEPLOYER_CONFIG_DIR` | Secrets and GitHub files |
| `VPS_DEPLOYER_DATA_DIR` | Database directory |
| `VPS_DEPLOYER_DATABASE_PATH` | SQLite file |
| `VPS_DEPLOYER_APPS_ROOT` | Application files |
| `VPS_DEPLOYER_RUNTIME` | `process`, `systemd`, or `auto` |
| `VPS_DEPLOYER_RELEASE_RETENTION` | Successful releases to keep (default 5) |

Secrets in the config directory use mode `600`.
