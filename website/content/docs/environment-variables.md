---
title: Environment variables
summary: Create and edit project environment values on this VPS.
---

Use the Environment variables section when creating a project or opening an existing project. Upload a UTF-8 `.env` file, paste assignments, or enter names and values in fields. Inputs merge in that order; the last assignment wins.

```dotenv
# This is a comment and is ignored.
COLOR=#ffffff
API_KEY="#literal-value" # This trailing comment is ignored.
EMPTY=
```

Values beginning with `#` are preserved. Lines beginning with `#` are comments, including commented-out assignments. Values are literal: shell commands and variable references are not expanded. Values must fit on a single line, and each submission is limited to 64 KiB. `HOST` and `PORT` are managed by VPS Deployer.

On an existing project's page, add or replace variables using the same inputs. Omitted variables retain their values. Select saved variable names to remove them, then choose **Save environment variables**. Saved values remain hidden. Redeploy after saving to apply changes to both builds and application processes; a restart applies runtime-only changes.

For CLI project creation, use `--env-file .env` or repeat `--env KEY=value`. Existing projects can also be updated with `PATCH /api/projects/{project}/environment`, supplying an `environment` string and an optional `remove` array of variable names. The response lists names only. Updating and removing the same name in one request is rejected.

Variables are stored in the local SQLite database. Builds and application processes receive them, and systemd uses a private mode-0600 environment file. Stored values are redacted from deployment logs.
