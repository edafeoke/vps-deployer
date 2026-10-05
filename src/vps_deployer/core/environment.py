"""Literal dotenv inputs; no shell expansion or evaluation."""

import os
from pathlib import Path

from vps_deployer.core.validation import ENV_NAME_RE, ValidationError


def parse_environment(text: str) -> dict[str, str]:
    if len(text.encode("utf-8")) > 65536:
        raise ValidationError("Environment input must be at most 64 KiB")
    result = {}
    for number, line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not ENV_NAME_RE.fullmatch(key) or "\x00" in value:
            raise ValidationError(f"Invalid environment assignment on line {number}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValidationError(f"Unclosed environment quote on line {number}")
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        if key in {"HOST", "PORT"}:
            raise ValidationError("HOST and PORT are managed by VPS Deployer")
        result[key] = value
    return result


def write_environment(root: Path, values: dict[str, str]) -> None:
    shared = root / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    path = shared / "env"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        os.chmod(path, 0o600)
        for key, value in values.items():
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            stream.write(f'{key}="{escaped}"\n')


def project_environment(project, settings=None):
    from sqlmodel import Session, select

    from vps_deployer.db.models import EnvironmentVariable
    from vps_deployer.db.session import get_engine

    with Session(get_engine(settings)) as session:
        rows = session.exec(
            select(EnvironmentVariable).where(EnvironmentVariable.project_id == project.id)
        ).all()
        return {row.key: row.value for row in rows}
