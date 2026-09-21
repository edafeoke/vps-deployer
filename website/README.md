# VPS Deployer website

Public site for `https://vps-deployer.centralstackhq.com`.

It serves the installer, documentation, and release archives. It does not register VPS instances or run deployments.

```bash
cd website
npm install
npm run dev
```

`predev` / `prebuild` copy `installer/install.sh` and build `public/releases/vps-deployer-<version>.tar.gz` from the parent `pyproject.toml` (excluding this website).
