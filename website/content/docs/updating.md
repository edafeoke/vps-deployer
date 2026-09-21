---
title: Updating
summary: Update VPS Deployer on this VPS.
---

```bash
sudo vps-deployer update
sudo vps-deployer update --yes
sudo vps-deployer update --version 0.3.0
sudo vps-deployer update --source /path/to/vps-deployer
sudo vps-deployer update --force
```

Must run as root. The command asks for confirmation unless `--yes`. `--source` and `--version` cannot be used together.

It reads the installed version, then uses `--version` or `GET https://vps-deployer.onebitstack.com/releases/latest.txt`. If those versions match, it stops unless you pass `--force`.

Then it downloads `install.sh` over HTTPS and re-runs the installer. The installer snapshots `/opt/vps-deployer/app`, preserves `/etc/vps-deployer`, the SQLite database, and `/var/www/apps`, migrates, restarts `vps-deployer.service`, checks `/health`, and restores the previous platform files if startup fails.

Updating VPS Deployer does not restart or replace your deployed applications.
