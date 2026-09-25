---
title: HTTPS
summary: Use Let's Encrypt or existing certificates, including Cloudflare Origin CA.
---

```bash
vps-deployer ssl enable my-next-app --email ops@example.com
vps-deployer ssl status my-next-app
vps-deployer ssl renew
```

Certificates live in `/etc/letsencrypt/live/<hostname>/`. The helper runs `certbot certonly --webroot` with a fixed argument list. Port 80 keeps `/.well-known/acme-challenge/` and redirects other HTTP traffic to HTTPS.

After you add a hostname, run `ssl enable` again. Private keys are never stored in SQLite or logs.

Local development writes a short-lived self-signed certificate under the configured SSL directory.

## External certificates / Cloudflare Origin CA

Create a project and attach its domain. Obtain a PEM certificate and matching unencrypted private key from your provider. For Cloudflare, create an **Origin CA** certificate covering every attached hostname (include the apex and `*.example.com` if needed). Its browser-facing Universal SSL certificate is separate and is not installed here.

Provide the files' existing absolute paths on the VPS (`.pem`, `.crt` or `.key`). VPS Deployer automatically copies and validates them into files directly under `/etc/ssl/vps-deployer/<project>/`. You do not need to move or rename the source files yourself. Regular-file symlink sources, such as Let's Encrypt paths, are supported; destination directories must not be symlinks or writable by non-root users.

```bash
vps-deployer ssl external my-next-app \
  --certificate /home/ubuntu/certificates/origin.pem \
  --key /home/ubuntu/certificates/origin.key
vps-deployer deploy my-next-app --wait
vps-deployer ssl status my-next-app
vps-deployer nginx show my-next-app
```

Alternatively, open the project's **External SSL / Cloudflare Origin CA** form, enter the two source paths, apply, then Deploy. The helper creates root-owned copies with unique filenames (certificate mode `644`, key mode `600`), validates the copied pair, and configures Nginx to use those paths. Source files and previously active copies are retained. The panel does not upload local-computer files or expose private-key contents. Files must already be on the VPS.

Before activation, the helper checks validity dates, key matching, and coverage of all attached hostnames including `www`. This checks the supplied certificate, not public CA trust. Nginx then tests the configuration and reloads. External settings persist across deployments. An additional domain is rejected if the certificate does not cover it.

For Cloudflare, enable proxying on the DNS records and use **Full (strict)**. Origin CA certificates secure Cloudflare-to-origin traffic; direct browser requests can report an untrusted certificate. Flexible mode is unsuitable for this HTTPS-redirect configuration. See [Cloudflare Origin CA](https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/) and [Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/).

External certificates are not renewed by `ssl renew`. Reapply `ssl external` with renewed source files; each import creates a new pair so it cannot overwrite an active key during validation. Old copies are retained for recovery and require manual cleanup when no longer referenced. Generated sites with custom overrides must be reset first. A transferred site with one explicit TLS pair can replace that pair directly without losing its custom Nginx settings. A transferred HTTP-only site must have its TLS server block configured manually first. Automatic Let's Encrypt/domain regeneration is disabled for transferred sites. The panel and `ssl status` show paths, never PEM key contents.

Local development uses `<VPS_DEPLOYER_SSL_DIR>/<project>/` and validates PEM data with OpenSSL under the local user. Production requires the updated 0.6.0 helper; update the installation before using these commands.
