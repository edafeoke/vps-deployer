---
title: Uninstall
summary: Intended uninstall behavior. Not shipped yet.
---

Uninstall is not in this release. The intended default is to remove VPS Deployer itself and keep your applications, nginx sites, certificates, and application data unless you pass an explicit `--purge`.

Until then, stop and disable the platform unit only if you intend to take the API down:

```bash
sudo systemctl disable --now vps-deployer
```

That does not remove `/var/www/apps` or `vps-deployer-app-<project>.service` units.
