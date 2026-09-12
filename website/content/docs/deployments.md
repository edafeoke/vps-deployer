---
title: Deployments
summary: How a release is fetched, built, health-checked, and activated.
---

```bash
vps-deployer deploy my-next-app
vps-deployer deploy my-next-app --commit <sha> --wait
```

The CLI and webhook only enqueue work. A worker on this VPS:

1. Creates a new release directory
2. Fetches the repository and checks out the commit
3. Installs dependencies and builds
4. Starts a candidate on `127.0.0.1:<port>` when the runtime needs a process
5. Health-checks the candidate
6. Switches `current` only after the candidate is healthy
7. Marks `SUCCESS` or `FAILED`

A failed candidate must not replace a working `current` release. One `RUNNING` deployment per project. Additional requests stay `QUEUED` (FIFO).

Release files live under `/var/www/apps/<project>/releases/`. `current` is a symlink. Default retention is 5 successful releases. The active release is never deleted.
