---
title: Uninstall
summary: Remove VPS Deployer from this VPS.
---

```bash
sudo vps-deployer uninstall
sudo vps-deployer uninstall --yes
sudo vps-deployer uninstall --purge --yes
```

Must run as root. Default removal stops `vps-deployer.service` and deletes the platform only:

- `/usr/local/bin/vps-deployer`
- `/usr/local/libexec/vps-deployer-helper`
- `/etc/sudoers.d/vps-deployer`
- `/etc/systemd/system/vps-deployer.service`
- dashboard nginx site `vps-deployer.conf`
- `/opt/vps-deployer`
- `/etc/vps-deployer`
- `/var/lib/vps-deployer`
- `/var/log/vps-deployer`

Then `systemctl daemon-reload` and `nginx -t && systemctl reload nginx`.

`--purge` also removes `vps-deployer-app-*.service` units, `vps-deployer-<project>.conf` sites, `/var/www/apps`, and the `vps-deployer` user.

Your applications, app nginx sites, certificates, and `/var/www/certbot` stay unless you pass `--purge`. Let's Encrypt files under `/etc/letsencrypt` are never deleted.
