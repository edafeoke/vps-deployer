---
title: Getting started
summary: Install VPS Deployer on your VPS and open the local dashboard.
---

VPS Deployer is a self-hosted platform. You install it on your VPS. That machine becomes the deployment platform. This website does not register your VPS or run your deployments.

## 1. Install on your VPS

On Ubuntu 22.04+, Ubuntu 24.04+, or Debian 12+:

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

The API listens on `127.0.0.1:5100`. It is not public.

## 3. Open the local dashboard

```bash
vps-deployer dashboard
```

From another computer, tunnel to that VPS:

```bash
ssh -L 5100:127.0.0.1:5100 user@your-vps
```

Then open `http://127.0.0.1:5100/`. That page manages only the machine you installed on.

## 4. Configure GitHub and add a project

```bash
vps-deployer github configure --app-id <id> --key-file ./github-app.pem --webhook-secret '<secret>'
vps-deployer project add my-next-app --repository example/my-next-app
vps-deployer deploy my-next-app
```

See [First project](/docs/first-project) and [GitHub](/docs/github).
