---
title: GitHub
summary: Store a GitHub App on your VPS and queue deploys from webhooks.
---

Open **Settings** on this VPS dashboard:

1. Publish a hostname and enable HTTPS. Webhooks cannot reach `127.0.0.1`.
2. Select **Connect GitHub**.
3. GitHub creates a private App with the detected webhook URL, **Contents: Read-only**
   permission, and **push** events.
4. Choose the account or organization and repositories that the App may access.

GitHub generates the App ID, private key, and webhook secret. VPS Deployer receives
them through GitHub's one-time App Manifest handshake and stores them automatically.
No credentials need to be copied into the dashboard.

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
The manual credential form remains available under **Manual GitHub App setup**.

## Webhook

GitHub should POST to this VPS at `/api/github/webhook`. The handler verifies `X-Hub-Signature-256`, matches `owner/name` and branch to a local project, inserts a `QUEUED` deployment, and returns immediately. It does not build or restart applications.

Expose the webhook only as you choose (SSH tunnel, private network, or the public dashboard hostname). The VPS Deployer API still binds to localhost. `POST /api/github/webhook` does not use the dashboard login; it still requires HMAC.

## What this website never does

This site does not store your GitHub App private key or create an account for you.
