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
            quote = value[0]
            chars = []
            index = 1
            while index < len(value):
                char = value[index]
                if char == quote:
                    trailing = value[index + 1 :].strip()
                    if trailing and not trailing.startswith("#"):
                        raise ValidationError(f"Invalid quoted environment value on line {number}")
                    break
                if char == "\\" and index + 1 < len(value) and value[index + 1] in (quote, "\\"):
                    index += 1
                    char = value[index]
                chars.append(char)
                index += 1
            else:
                raise ValidationError(f"Unclosed environment quote on line {number}")
            value = "".join(chars)
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


def merge_environment_inputs(text, upload=None, keys=None, values=None) -> str:
    """Normalize panel inputs, sharing validation between create and edit."""
    if upload and upload.filename:
        raw = upload.file.read(65537)
        if len(raw) > 65536:
            raise ValidationError("Environment input must be at most 64 KiB")
        try:
            text = raw.decode("utf-8-sig") + "\n" + text
        except UnicodeDecodeError as exc:
            raise ValidationError("Environment file must be UTF-8 text") from exc
    if len(keys or []) != len(values or []):
        raise ValidationError("Each environment variable needs a name and value")
    for key, value in zip(keys or [], values or [], strict=True):
        if not key.strip():
            if value:
                raise ValidationError("Each environment value needs a name")
            continue
        if not ENV_NAME_RE.fullmatch(key.strip()):
            raise ValidationError("Invalid environment variable name")
        if any(char in value for char in "\r\n"):
            raise ValidationError("Environment fields must be single-line values")
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        text += f'\n{key.strip()}="{escaped}"'
    parse_environment(text)
    return text


def update_environment(name, text, remove=(), settings=None) -> list[str]:
    from datetime import UTC, datetime

    from sqlmodel import Session, select

    from vps_deployer.core.projects import get_project
    from vps_deployer.db.models import EnvironmentVariable
    from vps_deployer.db.session import get_engine

    values = parse_environment(text)
    for key in remove:
        if not ENV_NAME_RE.fullmatch(key):
            raise ValidationError("Invalid environment variable name")
    if set(remove) & values.keys():
        raise ValidationError("A variable cannot be updated and removed in the same submission")
    project = get_project(name, settings)
    assert project.id is not None
    with Session(get_engine(settings)) as session:
        rows = session.exec(
            select(EnvironmentVariable).where(EnvironmentVariable.project_id == project.id)
        ).all()
        existing = {row.key: row for row in rows}
        for row in rows:
            if row.key in remove:
                session.delete(row)
            elif row.key in values:
                row.value = values[row.key]
                session.add(row)
        for key, value in values.items():
            if key not in existing:
                session.add(EnvironmentVariable(project_id=project.id, key=key, value=value))
        project.updated_at = datetime.now(UTC)
        session.add(project)
        session.commit()
    return sorted((existing.keys() - set(remove)) | values.keys())
