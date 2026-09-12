---
title: Logs
summary: Read deployment logs and application process logs on this VPS.
---

```bash
vps-deployer logs my-next-app
vps-deployer logs my-next-app --deployment 3
vps-deployer logs my-next-app --service
```

Deployment logs are stored locally. Tokens and private keys must not appear in them. Service logs come from the application systemd unit or the local process runtime.

The local dashboard shows the latest deployment log on the project page.
