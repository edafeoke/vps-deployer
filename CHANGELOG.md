# Changelog

## 0.7.0 — 2026-09-25

- Refresh the public documentation site with a shadcn-inspired dark console theme: semantic color tokens, amber primary actions, rounded cards, stronger navigation, sticky docs navigation, terminal code blocks and responsive mobile layout.
- Bump the package, installer and public release archive to 0.7.0 so users can install the authenticated panel and theme updates.

## 0.6.0 — 2026-09-25

- External SSL now accepts existing absolute source paths and automatically copies validated PEM files directly into `/etc/ssl/vps-deployer/<project>/`. Copies use unique filenames, root ownership and private-key mode 600; sources and previously active pairs are preserved.
- Added **Deploy replacement & transfer website** in the Nginx editor and `nginx handover` in the CLI. Build and health-check the target project before switching a single-backend/static Nginx site and stopping explicitly selected old systemd services.
- Preserve the source Nginx filename and custom settings, transfer domain ownership, copy existing TLS files, and keep transferred configurations intact on subsequent deployments.
- Added stale-config checks, protected/shared-service guards, failed-build isolation, Nginx backups and rollback on failed reload/service stop. Unsupported multi-backend, FastCGI and alias migrations fail explicitly.
- Handover does not copy databases, uploaded files or environment variables, disable service boot activation, or automatically migrate Docker/PM2 processes.

## 0.5.0 — 2026-09-25

- Add the Nginx menu with discovered configs, domains, ownership, enablement, and active configuration validation status, including unmanaged websites.
- Add host config editing with save/test, save/reload, stale-write protection, recoverable backups, and rollback after validation/reload failure. Keep privileged file/module directives unchanged.
- Add enable, disable, and delete website controls with typed confirmation for disruptive actions. Application files and certificates are retained.
- Add Services & processes with systemd inventory, process names, TCP/Unix listeners, working directories, and Nginx links, including named upstream matching.
- Add start/stop/restart controls for application services while protecting critical infrastructure services.
- Adopt existing websites in place and link an optional service. Imported apps appear in Projects and Services without changing deployment paths or creating Git releases.
- Install a root-owned standalone host helper launched with isolated system Python; include it in installer backup/rollback and uninstall handling.
- Preserve manually disabled managed sites across deployments; reset a project's Nginx config to regenerate a deleted/disabled site.

## 0.4.0 — 2026-09-25

- Show installed Nginx config, app directory, current release, web roots, upstreams, certificate paths, and private key paths in the dashboard and CLI.
- Add `nginx show`, `nginx edit`, `nginx apply --file`, and `nginx reset`, plus GET/PUT/DELETE Nginx API endpoints. Saved edits survive deployments; reset explicitly returns to generated config.
- Support request-size and proxy-timeout edits within the restricted helper's directive allowlist. Routing and TLS stay tied to domain/SSL controls.
- Add external SSL configuration from existing certificate/key files, including Cloudflare Origin CA. Check validity, hostname coverage, key matching, and production file permissions without returning key contents.
- Restore previous project Nginx files and enabled symlinks when configuration testing or reload fails.
- Preserve in-progress dashboard edits during deployment auto-refresh.
- Ensure Let's Encrypt certificates cover all names served by the shared project HTTPS block, even when a certificate name is selected.

Earlier release history is maintained in the website changelog (`website/lib/releases.ts`).
