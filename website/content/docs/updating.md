---
title: Updating
summary: How a future platform update is intended to work.
---

`vps-deployer update` is not in this release. The intended flow:

1. Detect the current version
2. Download and verify the new release from this website
3. Install platform files
4. Preserve configuration, the database, and your applications
5. Run migrations
6. Restart `vps-deployer.service`
7. Health-check; roll back the platform update if startup fails

Updating VPS Deployer must not restart or replace your deployed applications.

Until that command exists, re-run the installer with `--source` or `--version`. Config and `/var/www/apps` are preserved.
