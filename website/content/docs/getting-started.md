---
title: Getting started
summary: Install VPS Deployer on your VPS and open the local dashboard.
---

VPS Deployer is a self-hosted platform. You install it on your VPS. That machine becomes the deployment platform. This website does not register your VPS or run your deployments.

## 1. Install on your VPS

On Ubuntu 22.04 LTS or a newer LTS release, or Debian 12+:

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash
```

To read the installer first:

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh -o install.sh
less install.sh
sudo bash install.sh
```

## 2. Confirm the installation

```bash
vps-deployer version
vps-deployer status
vps-deployer doctor
```

The API listens on `127.0.0.1:5100`. It is not bound to the public internet.

## 3. Open the dashboard

```bash
vps-deployer dashboard
vps-deployer dashboard enable --host panel.example.com
vps-deployer dashboard ssl --email ops@example.com
```

`enable` publishes the same console through nginx. Dashboard requests—including direct localhost access after a password is configured—require a password. `--ip` uses the VPS public IPv4 address (HTTP only). An SSH tunnel is still optional:

```bash
ssh -L 5100:127.0.0.1:5100 user@your-vps
```

That page manages only the machine you installed on.

The dashboard hostname is independent from the public documentation and update site.
For example, this VPS may use `https://vps-deployer.centralstackhq.com`, while
installers and updates continue to come from `https://vps-deployer.onebitstack.com`.

## 4. Configure GitHub and add a project

On the dashboard, open **Settings**, publish a hostname, enable HTTPS, and select
**Connect GitHub**. VPS Deployer identifies the webhook URL and asks GitHub to generate
the App ID, private key, and webhook secret. Choose the repositories during GitHub's
installation step; no credentials need to be copied manually.

CLI is the same flow:

```bash
vps-deployer github configure --app-id <id> --key-file ./github-app.pem --webhook-secret '<secret>'
vps-deployer github status
vps-deployer project add my-next-app --repository example/my-next-app
vps-deployer deploy my-next-app
```

See [First project](/docs/first-project) and [GitHub](/docs/github).
