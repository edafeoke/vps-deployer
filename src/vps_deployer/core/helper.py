from __future__ import annotations

import os
import subprocess
from pathlib import Path

from vps_deployer.core.config import Settings, get_settings

DEFAULT_HELPER = Path("/usr/local/libexec/vps-deployer-helper")


class HelperError(RuntimeError):
    """Raised when the privileged helper is missing or rejects an action."""


def helper_path(settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    if current.helper_path is not None:
        return Path(current.helper_path)
    return DEFAULT_HELPER


def helper_available(settings: Settings | None = None) -> bool:
    return helper_path(settings).is_file()


def run_helper(
    *args: str,
    settings: Settings | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    current = settings or get_settings()
    path = helper_path(current)
    if not path.is_file():
        raise HelperError("Privileged helper is not installed")
    command = [str(path), *args]
    if current.helper_sudo and os.geteuid() != 0:
        command = ["sudo", "-n", "--", *command]
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        input=stdin,
    )


def require_helper(
    *args: str,
    settings: Settings | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = run_helper(*args, settings=settings, stdin=stdin)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "helper failed").strip()
        raise HelperError(detail)
    return result
