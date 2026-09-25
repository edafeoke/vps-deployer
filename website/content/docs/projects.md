---
title: Projects
summary: Create, import, inspect and manage applications on this VPS.
---

The **Projects** page also lists websites imported from the **Nginx** menu. Importing adopts an existing configuration and optional systemd service in place, preserving its files and running processes. Imported apps have operational controls but do not use Git releases. See [Nginx and importing existing websites](/docs/nginx).

To replace an existing application with Git deployments, create a project without a domain and use **Replace with a deployed project** in the old site's Nginx editor. The replacement is deployed and health-checked before traffic is switched and selected old services are stopped. This transfers Nginx settings and domains, not application data or environment variables. See [website handover](/docs/nginx).

## Services & processes

The **Services & processes** menu lists systemd services (including installed inactive services), process names/PIDs/users, TCP and Unix listeners, working directories and associated Nginx configs. Direct loopback upstreams, named upstream groups and Unix sockets can be correlated with a service; imported apps can also specify an explicit service link. These links are inferred, not proof that a backend is healthy.

Start, stop and restart application services from their **Manage** controls. Stop/restart require typing the exact unit name. Critical infrastructure (SSH, Nginx, networking, systemd, container managers and VPS Deployer itself) is protected; use dedicated settings or SSH for those. Stopping a service does not disable its boot configuration or other activation triggers.

Unsupervised processes and processes managed by Docker, PM2 or user service managers are visible when the host can discover them; this panel does not directly kill PIDs or manage individual containers. Use their owning system service where appropriate, or their native manager. Process arguments and environments are omitted because they can contain credentials. Static websites have a separate list because they need no app process.

## Git-based deployment projects

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
