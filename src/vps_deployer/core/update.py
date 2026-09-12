from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vps_deployer.core.config import DEFAULT_SITE_URL, get_settings
from vps_deployer.core.version import get_version

SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$")

CommandRunner = Callable[[list[str]], int]
LatestFetcher = Callable[[str], str]
InstallerDownloader = Callable[[str, Path], None]


class UpdateError(RuntimeError):
    """Raised when the platform update cannot run."""


@dataclass(frozen=True)
class UpdatePlan:
    current: str
    target: str | None
    source: Path | None
    skipped: bool
    message: str

    def installer_argv(self, install_sh: Path) -> list[str]:
        if self.source is not None:
            return ["bash", str(install_sh), "--source", str(self.source)]
        if self.target is None:
            raise UpdateError("No target version.")
        return ["bash", str(install_sh), "--version", self.target]


@dataclass(frozen=True)
class UpdateResult:
    current: str
    target: str | None
    skipped: bool
    message: str
    installer_argv: list[str] | None = None


def is_root() -> bool:
    return os.geteuid() == 0


def is_https_url(url: str) -> bool:
    return url.startswith("https://")


def validate_semver(version: str) -> bool:
    return bool(SEMVER_RE.fullmatch(version))


def parse_latest_txt(body: str) -> str:
    version = body.strip()
    if not validate_semver(version):
        raise UpdateError(f"Invalid version: {version or '(empty)'}")
    return version


def normalize_site_url(site_url: str) -> str:
    url = site_url.strip().rstrip("/")
    if not is_https_url(url):
        raise UpdateError("Refusing non-HTTPS download.")
    return url


def build_installer_argv(
    install_sh: Path,
    *,
    version: str | None = None,
    source: Path | None = None,
) -> list[str]:
    if version and source is not None:
        raise UpdateError("--source and --version cannot be used together.")
    if source is not None:
        return ["bash", str(install_sh), "--source", str(source)]
    if version:
        return ["bash", str(install_sh), "--version", version]
    raise UpdateError("A target version or --source path is required.")


def _curl_get(url: str) -> str:
    if not is_https_url(url):
        raise UpdateError("Refusing non-HTTPS download.")
    result = subprocess.run(
        ["curl", "-fsSL", url],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise UpdateError(detail or f"Failed to download {url}")
    return result.stdout


def _curl_download(url: str, dest: Path) -> None:
    if not is_https_url(url):
        raise UpdateError("Refusing non-HTTPS download.")
    result = subprocess.run(
        ["curl", "-fsSL", url, "-o", str(dest)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise UpdateError(detail or f"Failed to download {url}")


def _exec_installer(argv: list[str]) -> int:
    os.execvp(argv[0], argv)
    return 1


def plan_update(
    *,
    version: str | None = None,
    source: Path | None = None,
    force: bool = False,
    current_version: str | None = None,
    site_url: str | None = None,
    fetch_latest: LatestFetcher | None = None,
) -> UpdatePlan:
    if version and source is not None:
        raise UpdateError("--source and --version cannot be used together.")
    current = current_version if current_version is not None else get_version()
    if source is not None:
        resolved = source.expanduser()
        if not resolved.is_dir():
            raise UpdateError(f"Source path does not exist: {source}")
        return UpdatePlan(
            current=current,
            target=None,
            source=resolved.resolve(),
            skipped=False,
            message="",
        )
    target = version
    if target is None:
        base = normalize_site_url(site_url or DEFAULT_SITE_URL)
        fetch = fetch_latest or _curl_get
        target = parse_latest_txt(fetch(f"{base}/releases/latest.txt"))
    elif not validate_semver(target):
        raise UpdateError(f"Invalid version: {target}")
    if target == current and not force:
        return UpdatePlan(
            current=current,
            target=target,
            source=None,
            skipped=True,
            message=f"VPS Deployer {current} is already current.",
        )
    return UpdatePlan(
        current=current,
        target=target,
        source=None,
        skipped=False,
        message="",
    )


def run_update(
    *,
    version: str | None = None,
    source: Path | None = None,
    force: bool = False,
    require_root: bool = True,
    current_version: str | None = None,
    site_url: str | None = None,
    fetch_latest: LatestFetcher | None = None,
    download_installer: InstallerDownloader | None = None,
    runner: CommandRunner | None = None,
) -> UpdateResult:
    if require_root and not is_root():
        raise UpdateError("This command must run as root (sudo).")
    base = normalize_site_url(site_url or get_settings().site_url)
    plan = plan_update(
        version=version,
        source=source,
        force=force,
        current_version=current_version,
        site_url=base,
        fetch_latest=fetch_latest,
    )
    if plan.skipped:
        return UpdateResult(
            current=plan.current,
            target=plan.target,
            skipped=True,
            message=plan.message,
        )
    fd, path = tempfile.mkstemp(prefix="vps-deployer-install-", suffix=".sh")
    os.close(fd)
    dest = Path(path)
    download = download_installer or _curl_download
    download(f"{base}/install.sh", dest)
    dest.chmod(0o755)
    argv = plan.installer_argv(dest)
    run = runner or _exec_installer
    try:
        code = run(argv)
        if code != 0:
            raise UpdateError(f"Installer exited with {code}.")
        return UpdateResult(
            current=plan.current,
            target=plan.target,
            skipped=False,
            message="",
            installer_argv=argv,
        )
    finally:
        dest.unlink(missing_ok=True)
