---
title: First project
summary: Add, deploy, and publish an application on this VPS.
---

A project is one application on this VPS. Adding it does not deploy it.

```bash
vps-deployer project add my-next-app --repository example/my-next-app
vps-deployer project show my-next-app
vps-deployer deploy my-next-app
```

Names must match `^[a-z][a-z0-9-]{1,62}$`. Runtimes: `nextjs`, `node`, `vite`, `static`, `fastapi`, `flask`, `laravel`, `php`. Process apps receive a localhost port in `33000–33999`.

## Domain and HTTPS

```bash
vps-deployer domain add my-next-app example.com --www
vps-deployer ssl enable my-next-app --email ops@example.com
```

Point DNS A/AAAA records for `example.com` (and `www` if you used `--www`) at this VPS before you enable HTTPS.

## Local dashboard

The same actions exist at `http://127.0.0.1:5100/projects/my-next-app` on that VPS, or on the public dashboard hostname after `vps-deployer dashboard enable`.

## Remove a project record

```bash
vps-deployer project remove my-next-app --yes
```

Application files on disk are kept.
