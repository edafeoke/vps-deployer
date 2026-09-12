# VPS Deployer website

Public site for `https://vps-deployer.onebitstack.com`.

It serves the installer, documentation, and release archives. It does not register VPS instances or run deployments.

```bash
cd website
npm install
npm run dev
```

`predev` / `prebuild` copy `installer/install.sh` and build `public/releases/vps-deployer-0.1.0.tar.gz` from the parent repository (excluding this website).
