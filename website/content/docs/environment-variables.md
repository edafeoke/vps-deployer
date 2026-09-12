---
title: Environment variables
summary: Project environment values stay on this VPS.
---

Each project can store environment variables in the local SQLite database. Secret values must not appear in deployment logs or the local dashboard.

A dedicated `vps-deployer env` command is not in this release. Until it is, keep production secrets in files your start command already reads (for example a dotenv file under the project `shared/` directory that you manage yourself).

When the CLI lands, `env list` will mask values by default.
