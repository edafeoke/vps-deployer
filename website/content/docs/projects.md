---
title: Projects
summary: Create, list, and remove applications on this VPS.
---

```bash
vps-deployer projects
vps-deployer project list
vps-deployer project add my-api --repository example/my-api --runtime fastapi
vps-deployer project show my-api
vps-deployer project remove my-api
```

Each project stores a name, GitHub repository, branch, runtime, localhost port, optional domain, systemd unit name `vps-deployer-app-<project>`, and a path under the apps root (`/var/www/apps/<project>` in production).

Process runtimes start as `vps-deployer-app-<project>.service`. Static and Vite projects have no process unit.

```bash
vps-deployer start my-api
vps-deployer stop my-api
vps-deployer restart my-api
```
