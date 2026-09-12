---
title: Installation
summary: How the installer works and how to review it.
---

The installer is `https://vps-deployer.onebitstack.com/install.sh`. It must run as root.

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash
```

Pin a version:

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash -s -- --version 0.1.0
```

Install from a local checkout:

```bash
sudo bash installer/install.sh --source /path/to/vps-deployer
```

## What it does

1. Detects OS, architecture, CPU, RAM, disk, and internet.
2. Rejects unsupported systems.
3. Installs git, Python, uv, nginx, and certbot.
4. Creates the `vps-deployer` system user.
5. Installs the application under `/opt/vps-deployer`.
6. Preserves existing config and the SQLite database.
7. Installs the CLI, privileged helper, sudoers snippet, and systemd unit.
8. Starts `vps-deployer.service` and checks `/health`.

A second run is safe. It must not delete `/var/www/apps`, nginx site files, application units, or the database.

## Layout

| Path | Purpose |
| --- | --- |
| `/opt/vps-deployer` | Installed application |
| `/etc/vps-deployer` | Config and secrets (mode 600) |
| `/var/lib/vps-deployer` | SQLite database |
| `/var/log/vps-deployer` | Installer and API logs |
| `/var/www/apps` | Your applications |
| `/usr/local/bin/vps-deployer` | CLI |
| `/usr/local/libexec/vps-deployer-helper` | Privileged helper |

## After install

```bash
vps-deployer doctor
systemctl status vps-deployer
```

Log: `/var/log/vps-deployer/installer.log`.
