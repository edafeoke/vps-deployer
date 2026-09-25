---
title: Nginx
summary: How site files are written, tested, and reloaded.
---

## Host-wide Nginx menu

Open **Nginx** in the web panel to discover files under `/etc/nginx`, including `nginx.conf`, `conf.d`, `sites-available`, `sites-enabled`, snippets and other files reported by `nginx -T` inside that directory. Enabled symlinks are grouped with their source file. Symlinks that escape the Nginx directory are shown as errors and cannot be edited. Non-default Nginx installations outside `/etc/nginx` are not managed by this inventory.

The table shows domains, roots/upstreams, ownership (deployed project, imported app, unmanaged), and validation:

| Status | Meaning |
| --- | --- |
| OK | The enabled configuration is included in a passing active-config test |
| Error | File access failed or Nginx attributed a validation error to this file |
| Unknown | Active config validation failed elsewhere, or Nginx is unavailable |
| Unchecked | Disabled/shared file not established as valid by the active-config test |

These are configuration checks, not HTTP/application health checks. A disabled file is not marked valid just because the other sites pass. Nginx validates syntax and referenced files with [`-t`/`-T`](https://nginx.org/en/docs/switches.html).

Click a filename to edit it. **Save & test** writes and checks the active configuration without reloading. **Save & reload** also requests a graceful Nginx reload. A failed check/reload restores previous files. Stale edits are rejected; reload the file and reapply your changes. Failed form submissions retain the edited text.

For existing configs, routing and tuning directives can be changed. New document roots must be under `/var/www` or `/srv`; new upstreams use loopback TCP addresses. Existing Unix-socket upstreams, certificate paths, includes and logging directives are preserved. New/changed privileged file, include, module and scripting directives are rejected, even if Nginx would accept their syntax. Git-managed project configs retain the narrower project editor rules below and save/apply as one operation.

**Disable website** removes enabled links or moves a standalone config to `/etc/nginx/disabled-sites/<original-directory>/`. **Enable website** restores inclusion. **Delete website config** removes the config and its enabled links. Disable/delete require typing the exact config ID. Application files, backend processes and certificates are not deleted; stop a backend through Services if required. Infrastructure/dashboard access has dedicated controls.

Backups are kept in `/var/backups/vps-deployer/nginx/site-*/` with a `manifest.json` listing the original paths and numbered copies (including symlinks). An administrator can restore the corresponding files from that backup over SSH, then test and reload Nginx. Backups are not rotated automatically. Configs referenced by other includes may fail removal; the operation rolls back if the full configuration stops validating.

Disabling/deleting a Git-managed project's site records its disabled state so subsequent deployments do not silently publish it again. **Reset to generated config** on the project page restores that site's generated config.

## Import an existing website

On an unmanaged site's editor, choose **Import into VPS Deployer**, enter a unique application name, and optionally select its systemd service. This adopts it in place: no file migration, restart, certificate replacement, Git clone or new release. Imported applications appear in **Projects** and **Services & processes** with the original config and service links.

Importing provides operational management without changing traffic. When ready to move to Git releases, use the replacement handover below. Sites managed by another tool may still be rewritten by that tool; importing does not disable it.

Local development uses `VPS_DEPLOYER_NGINX_DIR` and labels validation unverified. It simulates host config changes and keeps backups under the local data directory without testing/reloading a real Nginx daemon. Stopping old services during handover requires production systemd. Production requires the 0.7.0 helper installed by the normal updater.

## Deploy a replacement and transfer the website

Create a replacement Git project **without a domain**, configure its build/start settings, environment and data dependencies, then open the existing site's Nginx editor. Under **Replace with a deployed project**, select the replacement, enter the linked old systemd service names, and type the config ID to confirm. Leave services blank only for a static site.

```bash
vps-deployer project add replacement --repository example/app --runtime node
vps-deployer nginx handover replacement \
  --config sites-available/old-app \
  --service old-app.service
vps-deployer logs replacement
```

The deployment worker builds the replacement and runs the normal runtime/static health checks before touching the old site. It then preserves the existing Nginx filename and custom settings, changes its app destination to the new project's reserved port or `current` directory, copies and validates its certificate/key pair, tests and reloads Nginx, and stops the explicitly selected old services. Domain ownership moves to the project and any in-place import record is replaced by the project association. Later deployments preserve the transferred file instead of generating a second conflicting site.

Supported sources have one direct loopback HTTP backend or one static app root, with at most one explicit TLS pair. Multi-backend sites, named upstream groups, FastCGI, aliases, variable destinations and proxy/static mixed sites need manual migration. Old services must be linked to the source config and cannot be protected infrastructure, another deployment project, or a service shared by another enabled website. Environment variables, databases, uploads, background jobs and service boot activation are not migrated. Prepare these before confirming. Stopping is not disabling: socket/timer/boot triggers can restart a service.

A failed build leaves the old website untouched. Changes to the source file during deployment cancel cutover. A failed Nginx reload or service stop attempts to restart the old services and restore/reload the backed-up site. Errors include the backup path when recovery needs manual intervention. A healthy replacement is retained on its own port after a cutover failure so recovery does not remove a backend that may already be receiving traffic. Check deployment logs before retrying. Abrupt machine/process failure during cutover may require manual recovery from the root-owned backup.

Transferred sites can be edited from the host menu, project page or `nginx edit`. Server names and privileged directives remain protected. Reset/domain/Let's Encrypt regeneration is blocked to avoid discarding custom settings; existing TLS pairs can be replaced through External SSL. Disable/enable still work; deployments never republish a disabled site. Backups include `handover.json` recording the changed config revision and old services for recovery.

## Generated project sites

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
