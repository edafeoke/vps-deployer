---
title: GitHub
summary: Store a GitHub App on your VPS and queue deploys from webhooks.
---

GitHub credentials stay on your VPS:

- `{config_dir}/github-app.pem`
- `{config_dir}/github-webhook-secret`
- `{config_dir}/github.json` (app ID and installation ID)

Files are mode `600`. They are never stored in SQLite or deployment logs.

```bash
vps-deployer github configure --app-id 12345 --key-file ./github-app.pem --webhook-secret '<secret>'
vps-deployer github status
vps-deployer github repos
```

## Webhook

GitHub should POST to this VPS at `/api/github/webhook`. The handler verifies `X-Hub-Signature-256`, matches `owner/name` and branch to a local project, inserts a `QUEUED` deployment, and returns immediately. It does not build or restart applications.

Expose the webhook only as you choose (SSH tunnel, private network, or a reverse proxy you control). The VPS Deployer API still binds to localhost by default.

## What this website never does

This site does not store your GitHub App private key or create an account for you.
