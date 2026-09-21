---
title: CLI
summary: Commands for this VPS Deployer installation.
---

The CLI talks to `http://127.0.0.1:5100` except `version`, `doctor`, `dashboard`, `github configure` / `github status`, `update`, and `uninstall`.

```bash
vps-deployer version
vps-deployer status
vps-deployer doctor
vps-deployer dashboard
vps-deployer dashboard enable --host panel.example.com
vps-deployer dashboard enable --ip
vps-deployer dashboard password
vps-deployer dashboard ssl --email ops@example.com
vps-deployer dashboard disable
vps-deployer projects
vps-deployer project list
vps-deployer project add my-next-app --repository example/my-next-app
vps-deployer project show my-next-app
vps-deployer project remove my-next-app
vps-deployer github status
vps-deployer github configure --app-id 12345 --key-file ./github-app.pem --webhook-secret '<secret>'
vps-deployer github repos
vps-deployer deploy my-next-app
vps-deployer logs my-next-app
vps-deployer logs my-next-app --service
vps-deployer start my-next-app
vps-deployer stop my-next-app
vps-deployer restart my-next-app
vps-deployer domain add my-next-app example.com --www
vps-deployer domain list my-next-app
vps-deployer domain remove my-next-app example.com
vps-deployer ssl enable my-next-app --email ops@example.com
vps-deployer ssl status my-next-app
vps-deployer ssl renew
vps-deployer rollback my-next-app
sudo vps-deployer update
sudo vps-deployer update --yes
sudo vps-deployer update --version 0.3.0
sudo vps-deployer update --source /path/to/vps-deployer
sudo vps-deployer update --force
vps-deployer uninstall
vps-deployer uninstall --purge --yes
```

`github status` prints `webhook_url` after the dashboard is published. You can also finish GitHub setup on the dashboard **Settings** page.
