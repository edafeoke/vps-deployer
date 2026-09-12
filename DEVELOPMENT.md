# Development

This repository contains the VPS Deployer installation (Python API, CLI, installer). The public website is a later phase.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Git

systemd and nginx are optional on your laptop. `vps-deployer doctor` reports WARN when they are absent.

## Setup

```bash
uv sync --extra dev
```

Local data and config are created under `./.local/` on first run. That directory is gitignored.

## Run the API

```bash
uv run uvicorn vps_deployer.api.main:app --host 127.0.0.1 --port 5100
```

The API binds to localhost only.

```bash
curl -s http://127.0.0.1:5100/health
curl -s http://127.0.0.1:5100/api/status
```

## Run the CLI

```bash
uv run vps-deployer version
uv run vps-deployer status
uv run vps-deployer doctor
uv run vps-deployer projects
uv run vps-deployer project list
uv run vps-deployer project add my-next-app --repository example/my-next-app
uv run vps-deployer project show my-next-app
uv run vps-deployer project remove my-next-app --yes
uv run vps-deployer github status
uv run vps-deployer github configure --app-id 12345 --key-file ./github-app.pem --webhook-secret 'x'
uv run vps-deployer github repos
```

`version`, `doctor`, and `github` configure/status work without the API. `status` and project commands call `http://127.0.0.1:5100`.

## Tests

```bash
uv run pytest
```

Installer library tests do not require a live VPS.

## Lint and typecheck

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

## Database

SQLite via SQLModel. Alembic migrations live in `migrations/`.

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
```

Local development can also create tables on API startup when the local config allows it.

## Installer

The installer targets Ubuntu and Debian. On macOS, test the detection helpers:

```bash
bash tests/installer/run_lib_tests.sh
```

To install from this checkout onto a real VPS:

```bash
sudo bash installer/install.sh --source /path/to/vps-deployer
```

## Project layout

```
src/vps_deployer/     Python package (API, CLI, doctor, models)
installer/            install.sh and shared lib.sh
packaging/            systemd unit and privileged helper
migrations/           Alembic
tests/                pytest and installer tests
```

## Quality bar

Do not merge a phase until tests, lint, and typecheck pass, failure cases are handled, and these docs stay accurate.
