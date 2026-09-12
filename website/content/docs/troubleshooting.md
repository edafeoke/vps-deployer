---
title: Troubleshooting
summary: Doctor, logs, and common install failures.
---

```bash
vps-deployer doctor
vps-deployer status
systemctl status vps-deployer
journalctl -u vps-deployer
journalctl -u vps-deployer-app-my-next-app
```

Installer log: `/var/log/vps-deployer/installer.log`.

## `failed to open file .../uv.toml`

The installer ran `uv` from your home directory. Re-download `install.sh` from this site and run it again. Until that build is live, `cd /tmp` first:

```bash
cd /tmp
sudo bash /path/to/install.sh
```

## The public website is down

Deploy, rollback, logs, and the local dashboard still work. You only need the internet for GitHub, Let's Encrypt, DNS, and downloading updates.

## Unsupported operating system

Supported: Ubuntu 22.04+, Ubuntu 24.04+, Debian 12+. See [Requirements](/docs/requirements).

## Port 5100 already in use

Stop the old `uvicorn` or `vps-deployer.service` process, then start the current one. The local dashboard is `GET /` on that port.

## HTTPS fails

Confirm DNS points at this VPS, port 80 is reachable, and you re-ran `ssl enable` after adding the hostname.
