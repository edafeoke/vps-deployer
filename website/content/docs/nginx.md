---
title: Nginx
summary: How site files are written, tested, and reloaded.
---

Each project gets `vps-deployer-<project>.conf` in nginx sites-available/enabled (or `conf.d` on installations without sites-available).

HTTP (`listen 80`) either proxies a process app to `127.0.0.1:<port>` or serves static files from `/var/www/apps/<project>/current`. HTTPS adds `listen 443 ssl`.

The privileged helper installs the site, runs `nginx -t`, and reloads. A failed test rolls back that site file and leaves other sites untouched.

## Inspect paths and edit

Open a project's dashboard page for the installed site file, app directory, `current` symlink and resolved release, web roots, upstreams, and certificate/key paths. A reverse-proxy config identifies the port, not the application's filesystem path; the panel also uses the project record to show that path. Before a site is installed, the editor is labeled as a preview.

```bash
vps-deployer nginx show my-next-app
vps-deployer nginx show my-next-app --raw > my-next-app.conf
vps-deployer nginx edit my-next-app
vps-deployer nginx apply my-next-app --file ./my-next-app.conf
vps-deployer nginx reset my-next-app
```

`edit` opens `$VISUAL`/`$EDITOR`. The dashboard has the same save/apply and reset controls. `--raw` prints only configuration text for exporting. No certificate/key contents are returned.

The editor supports comments, `client_max_body_size` (1–9999m/k), and `proxy_read_timeout`, `proxy_connect_timeout`, and `proxy_send_timeout` (1–9999s). Keep existing routing and TLS declarations; manage those through the domain/SSL controls. This is a restricted project-site editor, not an editor for global Nginx config or unrelated sites.

Saved custom config is stored under `/etc/vps-deployer/sites/<project>.json` and reapplied on deployments. Reset it before changing domains or SSL; those operations reject custom mode before changing state. Manual on-disk changes outside the panel/CLI are not persisted as overrides.

Production saves run the helper allowlist, `nginx -t`, and reload. A failed test or reload restores the previous site file and enabled symlink. In local development, config is written to `VPS_DEPLOYER_NGINX_DIR` after application validation; no Nginx daemon test/reload is performed.

`include`, `alias`, and shell metacharacters are rejected. Application `proxy_pass` may only target `127.0.0.1` on ports `33000–33999`. The dashboard site `vps-deployer.conf` may proxy only to `127.0.0.1:5100`. TLS files use Let's Encrypt paths or project-scoped external certificate paths; see [HTTPS](/docs/ssl).
