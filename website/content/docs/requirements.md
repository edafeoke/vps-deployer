---
title: Requirements
summary: Operating systems and hardware for a VPS Deployer installation.
---

## Operating systems

- Ubuntu 22.04 LTS or newer
- Ubuntu 24.04 LTS or newer
- Debian 12 or newer

amd64 and arm64 are supported.

## Hardware

Recommended:

- 2 CPU cores
- 2 GB RAM
- 10 GB free disk

The installer refuses to continue below 512 MB RAM or 2 GB free disk. Actual needs depend on the applications you deploy.

## Access

- Root or sudo
- Outbound internet for GitHub, Let's Encrypt, OS packages, and updates
- Public IPv4 or IPv6 if you will serve `example.com` on ports 80 and 443

SSH (port 22) must stay reachable. The installer never runs `ufw reset`.

## Local development

macOS and other laptops can run the API and CLI. `vps-deployer doctor` reports WARN when systemd or nginx are missing. That is expected.
