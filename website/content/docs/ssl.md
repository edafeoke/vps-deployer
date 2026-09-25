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

Install the files on the VPS as root. The helper accepts external files directly under `/etc/ssl/vps-deployer/<project>/` with simple `.pem`, `.crt`, or `.key` filenames; it rejects symlinks and files writable by group/others. The key must be mode `600` or `400`.

```bash
sudo install -d -m 700 /etc/ssl/vps-deployer/my-next-app
sudo install -o root -g root -m 644 ./origin.pem /etc/ssl/vps-deployer/my-next-app/origin.pem
sudo install -o root -g root -m 600 ./origin.key /etc/ssl/vps-deployer/my-next-app/origin.key
vps-deployer ssl external my-next-app \
  --certificate /etc/ssl/vps-deployer/my-next-app/origin.pem \
  --key /etc/ssl/vps-deployer/my-next-app/origin.key
vps-deployer deploy my-next-app --wait
vps-deployer ssl status my-next-app
vps-deployer nginx show my-next-app
```

Alternatively, open the project's **External SSL / Cloudflare Origin CA** form, enter these two VPS paths, apply, then Deploy. Certificate files are installed through the terminal; the panel configures their paths and does not upload or expose private keys.

Before activation, the helper checks validity dates, key matching, and coverage of all attached hostnames including `www`. This checks the supplied certificate, not public CA trust. Nginx then tests the configuration and reloads. External settings persist across deployments. An additional domain is rejected if the certificate does not cover it.

For Cloudflare, enable proxying on the DNS records and use **Full (strict)**. Origin CA certificates secure Cloudflare-to-origin traffic; direct browser requests can report an untrusted certificate. Flexible mode is unsuitable for this HTTPS-redirect configuration. See [Cloudflare Origin CA](https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/) and [Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/).

External certificates are not renewed by `ssl renew`. Replace them with renewed files and reapply `ssl external` (reset custom Nginx config first if enabled). To return to Let's Encrypt, use `ssl enable`; externally supplied files are retained. The panel and `ssl status` show the provider and file paths, never PEM key contents.

Local development uses `<VPS_DEPLOYER_SSL_DIR>/<project>/` for external files and validates PEM data without root ownership requirements. Production requires the updated 0.4.0 helper; update the installation before using these commands.
