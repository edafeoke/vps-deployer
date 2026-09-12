from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vps_deployer.core.units import APP_SERVICE_PREFIX
from vps_deployer.core.validation import PROJECT_NAME_RE

PLATFORM_UNIT = "vps-deployer.service"
DASHBOARD_SITE = "vps-deployer.conf"
PLATFORM_USER = "vps-deployer"

CommandRunner = Callable[[list[str]], int]


class UninstallError(RuntimeError):
    """Raised when uninstall cannot run."""


@dataclass(frozen=True)
class UninstallLayout:
    bindir: Path = Path("/usr/local/bin")
    libexec: Path = Path("/usr/local/libexec")
    sudoers: Path = Path("/etc/sudoers.d/vps-deployer")
    systemd_dir: Path = Path("/etc/systemd/system")
    nginx_available: Path = Path("/etc/nginx/sites-available")
    nginx_enabled: Path = Path("/etc/nginx/sites-enabled")
    nginx_confd: Path = Path("/etc/nginx/conf.d")
    opt: Path = Path("/opt/vps-deployer")
    etc: Path = Path("/etc/vps-deployer")
    data: Path = Path("/var/lib/vps-deployer")
    logs: Path = Path("/var/log/vps-deployer")
    apps: Path = Path("/var/www/apps")

    @property
    def cli(self) -> Path:
        return self.bindir / "vps-deployer"

    @property
    def helper(self) -> Path:
        return self.libexec / "vps-deployer-helper"

    @property
    def platform_unit(self) -> Path:
        return self.systemd_dir / PLATFORM_UNIT


@dataclass
class UninstallPlan:
    units: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)
    purge: bool = False
    remove_user: bool = False


@dataclass
class UninstallResult:
    removed: list[str]
    skipped: list[str]


def is_root() -> bool:
    return os.geteuid() == 0


def _is_app_unit(name: str) -> bool:
    prefix = f"{APP_SERVICE_PREFIX}"
    if not name.startswith(prefix) or not name.endswith(".service"):
        return False
    project = name[len(prefix) : -len(".service")]
    return bool(PROJECT_NAME_RE.fullmatch(project))


def _is_app_site(name: str) -> bool:
    if name == DASHBOARD_SITE or not name.startswith("vps-deployer-") or not name.endswith(".conf"):
        return False
    project = name[len("vps-deployer-") : -len(".conf")]
    return bool(PROJECT_NAME_RE.fullmatch(project))


def _dashboard_sites(layout: UninstallLayout) -> list[Path]:
    return [
        layout.nginx_enabled / DASHBOARD_SITE,
        layout.nginx_available / DASHBOARD_SITE,
        layout.nginx_confd / DASHBOARD_SITE,
    ]


def _existing_app_units(layout: UninstallLayout) -> list[str]:
    if not layout.systemd_dir.is_dir():
        return []
    names: list[str] = []
    for path in sorted(layout.systemd_dir.iterdir()):
        if path.is_file() and _is_app_unit(path.name):
            names.append(path.name)
    return names


def _existing_app_sites(layout: UninstallLayout) -> list[Path]:
    found: list[Path] = []
    for directory in (layout.nginx_enabled, layout.nginx_available, layout.nginx_confd):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and _is_app_site(path.name):
                found.append(path)
    return found


def collect_uninstall_targets(
    purge: bool = False,
    layout: UninstallLayout | None = None,
) -> UninstallPlan:
    current = layout or UninstallLayout()
    files = [
        current.cli,
        current.helper,
        current.sudoers,
        current.platform_unit,
        *_dashboard_sites(current),
    ]
    directories = [current.opt, current.etc, current.data, current.logs]
    units = [PLATFORM_UNIT]
    if purge:
        units.extend(_existing_app_units(current))
        files.extend(_existing_app_sites(current))
        directories.append(current.apps)
    return UninstallPlan(
        units=units,
        files=files,
        directories=directories,
        purge=purge,
        remove_user=purge,
    )


def _default_runner(args: list[str]) -> int:
    binary = shutil.which(args[0])
    if binary is None:
        return 127
    command = [binary, *args[1:]]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    return result.returncode


def _stop_units(units: list[str], run: CommandRunner) -> None:
    for unit in units:
        run(["systemctl", "disable", "--now", unit])


def _reload_systemd(run: CommandRunner, skipped: list[str]) -> None:
    if run(["systemctl", "daemon-reload"]) == 127:
        skipped.append("systemctl daemon-reload skipped")


def _reload_nginx(run: CommandRunner, skipped: list[str]) -> None:
    code = run(["nginx", "-t"])
    if code == 127:
        skipped.append("nginx not available")
        return
    if code != 0:
        skipped.append("nginx -t failed")
        return
    reload_code = run(["systemctl", "reload", "nginx"])
    if reload_code == 127:
        run(["nginx", "-s", "reload"])


def _try_delete_account(command: str, label: str, skipped: list[str], removed: list[str]) -> None:
    if shutil.which(command) is None:
        return
    result = subprocess.run([command, PLATFORM_USER], check=False, capture_output=True)
    if result.returncode == 0:
        removed.append(f"{label} {PLATFORM_USER}")
    else:
        skipped.append(f"{label} {PLATFORM_USER}")


def _remove_user(skipped: list[str], removed: list[str]) -> None:
    _try_delete_account("userdel", "user", skipped, removed)
    _try_delete_account("groupdel", "group", skipped, removed)


def run_uninstall(
    *,
    purge: bool = False,
    layout: UninstallLayout | None = None,
    runner: CommandRunner | None = None,
    require_root: bool = True,
) -> UninstallResult:
    if require_root and not is_root():
        raise UninstallError("This command must run as root (sudo).")
    current = layout or UninstallLayout()
    plan = collect_uninstall_targets(purge, current)
    run = runner or _default_runner
    removed: list[str] = []
    skipped: list[str] = []

    _stop_units(plan.units, run)

    for path in plan.files:
        if path.is_symlink() or path.is_file():
            path.unlink()
            removed.append(str(path))
        else:
            skipped.append(str(path))

    for path in plan.directories:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))
        else:
            skipped.append(str(path))

    _reload_systemd(run, skipped)
    _reload_nginx(run, skipped)
    if plan.remove_user and current.etc == UninstallLayout().etc:
        _remove_user(skipped, removed)
    return UninstallResult(removed=removed, skipped=skipped)
