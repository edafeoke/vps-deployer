---
title: HTTPS
summary: Issue Let's Encrypt certificates through the privileged helper.
---

```bash
vps-deployer ssl enable my-next-app --email ops@example.com
vps-deployer ssl status my-next-app
vps-deployer ssl renew
```

Certificates live in `/etc/letsencrypt/live/<hostname>/`. The helper runs `certbot certonly --webroot` with a fixed argument list. Port 80 keeps `/.well-known/acme-challenge/` and redirects other HTTP traffic to HTTPS.

After you add a hostname, run `ssl enable` again. Private keys are never stored in SQLite or logs.

Local development writes a short-lived self-signed certificate under the configured SSL directory.
