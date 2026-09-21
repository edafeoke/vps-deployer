# Installation

This guide takes a fresh Ubuntu or Debian VPS to a running VPS Deployer installation.

You do not need an account on the VPS Deployer website.

## Prerequisites

Supported operating systems:

- Ubuntu 22.04 LTS or a newer LTS release
- Debian 12 or newer

Recommended minimum hardware:

- 2 CPU cores
- 2 GB RAM
- 10 GB free disk
- amd64 or arm64
- Root or sudo access
- Public IPv4 or IPv6 and internet access

Prepare your VPS:

1. Create or rent a VPS on a supported OS.
2. SSH in as a sudo-capable user.
3. Apply pending OS updates if you want a clean baseline.
4. Confirm you can reach the internet from the VPS.

## Quick install

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash
```

Optional version pin:

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh | sudo bash -s -- --version 0.3.3
```

## Review before installation

Because the installer runs as root, inspect it first:

```bash
curl -fsSL https://vps-deployer.onebitstack.com/install.sh -o install.sh
less install.sh
sudo bash install.sh
```

Debug output:

```bash
sudo bash install.sh --debug
```

Install from a local checkout (development):

```bash
sudo bash installer/install.sh --source /path/to/vps-deployer
```

## What the installer does

1. Detects root/sudo, OS, architecture, CPU, RAM, disk, and internet.
2. Rejects unsupported systems.
3. Installs git, Python, uv, nginx, and certbot.
4. Creates the `vps-deployer` system user.
5. Creates `/opt/vps-deployer`, `/etc/vps-deployer`, `/var/lib/vps-deployer`, `/var/log/vps-deployer`, and `/var/www/apps`.
6. Installs the application, CLI, privileged helper, sudoers snippet, and systemd unit.
7. Initializes the SQLite database if it does not already exist.
8. Starts `vps-deployer.service` and checks `/health`.

The installer is idempotent. Running it again preserves configuration, the database, your applications, nginx site files, and application systemd units. If the new platform files fail health checks, it restores the previous `/opt/vps-deployer/app`, CLI, helper, and systemd unit. Your applications are never rolled back.

To remove the platform later: `sudo vps-deployer uninstall`. Add `--purge` only if you also want applications deleted.

## Verify

```bash
vps-deployer version
vps-deployer status
vps-deployer doctor
```

Expected result: the service is running, the API answers on `127.0.0.1:5100`, and doctor reports PASS for the platform checks. Missing Node.js or an unconfigured GitHub App is a WARN, not a failed install.

## Next steps

1. Read the getting-started docs: <https://vps-deployer.onebitstack.com/docs/getting-started>
2. Create a GitHub App, then:

   ```bash
   vps-deployer github configure --app-id <id> --key-file ./github-app.pem --webhook-secret '<secret>'
   vps-deployer github repos
   ```

3. Add your first project, for example `my-next-app`.
4. Open the dashboard on the VPS (`http://127.0.0.1:5100/`), publish it, or tunnel to it:

   ```bash
   vps-deployer dashboard
   vps-deployer dashboard enable --host panel.example.com
   vps-deployer dashboard ssl --email ops@example.com
   ssh -L 5100:127.0.0.1:5100 user@your-vps
   ```

5. Deploy, attach `example.com`, and enable HTTPS:

   ```bash
   vps-deployer domain add my-next-app example.com --www
   vps-deployer ssl enable my-next-app --email ops@example.com
   ```

## Troubleshooting

Installation failed.

Log:

```text
/var/log/vps-deployer/installer.log
```

Useful commands:

```bash
vps-deployer doctor
systemctl status vps-deployer
journalctl -u vps-deployer
ss -ltnp
df -h
free -h
```

`Permission denied: '/etc/vps-deployer/config.env'`. The service user and the admin who ran the installer must be able to read `config.env`. The directory is `root:vps-deployer` mode `770`; the file is mode `640`. Re-download `install.sh` and re-run it, or fix the live VPS:

```bash
sudo chown root:vps-deployer /etc/vps-deployer
sudo chmod 770 /etc/vps-deployer
sudo chown vps-deployer:vps-deployer /etc/vps-deployer/config.env
sudo chmod 640 /etc/vps-deployer/config.env
sudo usermod -aG vps-deployer "$USER"
```

Then start a new SSH session (or run `newgrp vps-deployer`) so the group applies. Until then, `sudo vps-deployer dashboard` works.

`failed to open file .../uv.toml: Permission denied`. Re-download `install.sh` and re-run it. The installer now runs `uv` from `/opt/vps-deployer/app`, not from your home directory. Until that release is live, `cd /tmp` first.

Unsupported operating system. Supported systems are Ubuntu 22.04 LTS or a newer LTS release, and Debian 12+. See <https://vps-deployer.onebitstack.com/docs/requirements>.

## Uninstall

Uninstall is a later phase. The intended default is to remove VPS Deployer itself and keep your applications, nginx sites, certificates, and application data unless you pass an explicit `--purge`.
