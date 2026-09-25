from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from vps_deployer.core.config import Settings
from vps_deployer.core.validation import ValidationError, validate_project_name

_site_lock = RLock()


def site_mutation[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    """Keep dashboard/API threads and the deployment worker's site state consistent."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with _site_lock:
            return function(*args, **kwargs)

    return wrapped


def state_path(name: str, settings: Settings) -> Path:
    assert settings.config_dir is not None
    return settings.config_dir / "sites" / f"{validate_project_name(name)}.json"


def load_site_config(name: str, settings: Settings) -> dict[str, str]:
    path = state_path(name, settings)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_site_config(name: str, state: dict[str, str], settings: Settings) -> None:
    path = state_path(name, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(json.dumps(state) + "\n")
            file.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def require_generated_site(name: str, settings: Settings) -> None:
    if load_site_config(name, settings).get("custom"):
        raise ValidationError("Reset custom Nginx config before changing domains or SSL.")


def external_certificate_path(value: str, name: str, settings: Settings) -> str:
    base = Path("/etc/ssl/vps-deployer") / validate_project_name(name)
    if settings.nginx_dir is not None:
        assert settings.ssl_dir is not None
        base = settings.ssl_dir / name
    path = Path(value)
    if path.parent != base or not re.fullmatch(r"[a-zA-Z0-9_-]+\.(pem|crt|key)", path.name):
        raise ValidationError(f"Certificate and key must be files directly under {base}")
    if str(path) != value or not path.is_absolute():
        raise ValidationError("Use a canonical absolute certificate path")
    return value
