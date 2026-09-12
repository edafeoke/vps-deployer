---
title: Domains
summary: Attach hostnames on this VPS and write nginx site files.
---

```bash
vps-deployer domain add my-next-app example.com --www
vps-deployer domain list my-next-app
vps-deployer domain remove my-next-app example.com
```

Hostnames are unique on this VPS. Optional `www` is an extra `server_name`, not a second project.

DNS must point at this VPS. VPS Deployer does not change DNS at your registrar.
