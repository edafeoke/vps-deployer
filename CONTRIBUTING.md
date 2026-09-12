# Contributing

Thank you for helping improve VPS Deployer.

## Product rules

- Keep the website and the VPS installation independent.
- Do not add a multi-VPS dashboard, VPS registration, or a central deploy queue.
- Do not hardcode customer projects or domains.
- Use generic examples: `my-next-app`, `my-api`, `example.com`.
- Prefer CLI and API completeness over dashboard features.
- Do not introduce Kubernetes, Redis, PostgreSQL, or Docker unless there is a concrete requirement.

## Workflow

1. Read [ARCHITECTURE.md](ARCHITECTURE.md) and [DEVELOPMENT.md](DEVELOPMENT.md).
2. Inspect existing code before changing it.
3. Implement incrementally.
4. Add tests for success and failure cases.
5. Update documentation.

## Checks

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
cd website && npm run build
```

## Language

Prefer:

- "VPS Deployer installation"
- "your VPS"
- "your projects"
- "your applications"

Avoid:

- "connected server"
- "remote server"
- "server profile"
- "VPS fleet"
- "control plane"

except when comparing architectures.

## Security

See [SECURITY.md](SECURITY.md). Do not add arbitrary command execution, unrestricted sudo, or secret logging.
