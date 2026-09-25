# Changelog

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
