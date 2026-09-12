---
title: Rollback
summary: Restore the previous healthy release on this VPS.
---

```bash
vps-deployer rollback my-next-app
vps-deployer rollback my-next-app --to 3
```

Rollback finds the previous `SUCCESS` (or `ROLLED_BACK`) release that is not `current`, switches the symlink, restarts, health-checks, and records a `ROLLED_BACK` deployment.

It refuses while a deployment is `RUNNING`. If the restored release is unhealthy, `current` is put back. Failed or newer releases stay on disk. The active release is never deleted. Retention cleanup does not run on rollback.
