---
title: GitHub
summary: Store a GitHub App on your VPS and queue deploys from webhooks.
---

Open **Settings** on this VPS dashboard and follow the GitHub App walkthrough.

1. Publish a hostname if GitHub must reach this VPS. Webhooks cannot hit `127.0.0.1`.
2. Copy the webhook URL (`https://panel.example.com/api/github/webhook` when the dashboard is public).
3. Create a GitHub App at [github.com/settings/apps/new](https://github.com/settings/apps/new). Set the webhook URL and a webhook secret. Subscribe to **push**. Repository permissions: Contents Read-only (and Metadata).
4. Generate a private key and install the app on the account or organization.
5. Paste the App ID, PEM, webhook secret, and optional installation ID. Store them on this VPS.

GitHub credentials stay on your VPS:

- `{config_dir}/github-app.pem`
- `{config_dir}/github-webhook-secret`
- `{config_dir}/github.json` (app ID and installation ID)

Files are mode `600`. They are never stored in SQLite or deployment logs.

The service user must be able to create those files. Production `/etc/vps-deployer` is `root:vps-deployer` mode `770`. On an older install:

```bash
sudo chmod 770 /etc/vps-deployer
```

CLI is still available:

```bash
vps-deployer github configure --app-id 12345 --key-file ./github-app.pem --webhook-secret '<secret>'
vps-deployer github status
vps-deployer github repos
```

`github status` prints `webhook_path` and `webhook_url` (the full URL after you publish a dashboard host).

## Webhook

GitHub should POST to this VPS at `/api/github/webhook`. The handler verifies `X-Hub-Signature-256`, matches `owner/name` and branch to a local project, inserts a `QUEUED` deployment, and returns immediately. It does not build or restart applications.

Expose the webhook only as you choose (SSH tunnel, private network, or the public dashboard hostname). The VPS Deployer API still binds to localhost. `POST /api/github/webhook` does not use the dashboard login; it still requires HMAC.

## What this website never does

This site does not store your GitHub App private key or create an account for you.
