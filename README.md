# VPS Deployer

VPS Deployer is a self-hosted deployment platform that you install directly on your VPS.

It lets you deploy and manage applications on that VPS using GitHub, systemd, nginx, domains, HTTPS, deployment logs, health checks, and rollbacks.

You do not create an account on the VPS Deployer website to install or use it. The website distributes documentation and the installer. Your VPS becomes the deployment platform.

```
Visit the website
        ↓
Run install.sh on your VPS
        ↓
Configure GitHub
        ↓
Add an application
        ↓
Deploy and manage it on that VPS
```

## Installation

On Ubuntu 22.04 LTS or a newer LTS release, or Debian 12+:

```bash
curl -fsSL https://vps-deployer.centralstackhq.com/install.sh | sudo bash
```

To inspect the installer before running it:

```bash
curl -fsSL https://vps-deployer.centralstackhq.com/install.sh -o install.sh
less install.sh
sudo bash install.sh
```

Then:

```bash
vps-deployer version
vps-deployer status
vps-deployer doctor
```

## Requirements

- Ubuntu 22.04 LTS or a newer LTS release, or Debian 12+
- 2 CPU cores recommended
- 2 GB RAM recommended
- 10 GB free disk
- amd64 or arm64
- Root or sudo access
- Internet connectivity

Actual application requirements depend on what you deploy.

## Useful commands

```bash
vps-deployer version
vps-deployer status
vps-deployer doctor
vps-deployer projects
vps-deployer project list
vps-deployer project add my-next-app --repository example/my-next-app
vps-deployer project show my-next-app
vps-deployer project remove my-next-app
vps-deployer github status
vps-deployer github configure --app-id 12345 --key-file ./github-app.pem --webhook-secret '<secret>'
vps-deployer github repos
vps-deployer deploy my-next-app
vps-deployer logs my-next-app
vps-deployer logs my-next-app --service
vps-deployer start my-next-app
vps-deployer stop my-next-app
vps-deployer restart my-next-app
vps-deployer domain add my-next-app example.com --www
vps-deployer domain list my-next-app
vps-deployer domain remove my-next-app example.com
vps-deployer ssl enable my-next-app --email ops@example.com
vps-deployer ssl status my-next-app
vps-deployer ssl renew
vps-deployer rollback my-next-app
vps-deployer dashboard
```

The dashboard is `http://127.0.0.1:5100/` on that VPS. Publish it on a hostname or the VPS IP (password required), or tunnel:

```bash
vps-deployer dashboard enable --host panel.example.com
vps-deployer dashboard enable --ip
ssh -L 5100:127.0.0.1:5100 user@your-vps
```

After publishing a hostname and enabling HTTPS, open **Settings** and select
**Connect GitHub**. The GitHub App Manifest flow configures the webhook URL,
read-only repository permission, private key, and webhook secret automatically.

The public website is docs and the installer only. It does not register your VPS.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Installation](INSTALLATION.md)
- [Development](DEVELOPMENT.md)
- [Security](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

Public docs: <https://vps-deployer.centralstackhq.com/docs>

## Local development

See [DEVELOPMENT.md](DEVELOPMENT.md).

```bash
uv sync --extra dev
uv run vps-deployer version
uv run uvicorn vps_deployer.api.main:app --host 127.0.0.1 --port 5100
```

## License

See the repository license when published.
