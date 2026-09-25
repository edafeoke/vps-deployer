# Changelog

## 0.4.0 — 2026-09-25

- Show installed Nginx config, app directory, current release, web roots, upstreams, certificate paths, and private key paths in the dashboard and CLI.
- Add `nginx show`, `nginx edit`, `nginx apply --file`, and `nginx reset`, plus GET/PUT/DELETE Nginx API endpoints. Saved edits survive deployments; reset explicitly returns to generated config.
- Support request-size and proxy-timeout edits within the restricted helper's directive allowlist. Routing and TLS stay tied to domain/SSL controls.
- Add external SSL configuration from existing certificate/key files, including Cloudflare Origin CA. Check validity, hostname coverage, key matching, and production file permissions without returning key contents.
- Restore previous project Nginx files and enabled symlinks when configuration testing or reload fails.
- Preserve in-progress dashboard edits during deployment auto-refresh.
- Ensure Let's Encrypt certificates cover all names served by the shared project HTTPS block, even when a certificate name is selected.

Earlier release history is maintained in the website changelog (`website/lib/releases.ts`).
