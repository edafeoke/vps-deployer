from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import text

from vps_deployer.core.config import Settings, get_settings
from vps_deployer.core.version import get_version

Status = Literal["PASS", "WARN", "FAIL"]

SUPPORTED_OS_MESSAGE = (
    "Supported systems: Ubuntu 22.04+, Ubuntu 24.04+, Debian 12+. "
    "See https://vps-deployer.onebitstack.com/docs/requirements"
)


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _linux_os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.startswith("#"):
            continue
        key, value = raw.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _version_ge(current: str, minimum: str) -> bool:
    def parts(value: str) -> list[int]:
        out: list[int] = []
        for item in value.replace("-", ".").split("."):
            if item.isdigit():
                out.append(int(item))
            else:
                break
        return out or [0]

    left = parts(current)
    right = parts(minimum)
    size = max(len(left), len(right))
    left.extend([0] * (size - len(left)))
    right.extend([0] * (size - len(right)))
    return left >= right


def check_operating_system() -> CheckResult:
    system = platform.system()
    if system != "Linux":
        return CheckResult(
            "Operating system",
            "WARN",
            f"{system} is not a production target. {SUPPORTED_OS_MESSAGE}",
        )
    info = _linux_os_release()
    distro_id = info.get("ID", "").lower()
    version = info.get("VERSION_ID", "")
    pretty = info.get("PRETTY_NAME", f"{distro_id} {version}".strip() or "Linux")
    supported = False
    if distro_id == "ubuntu" and version and _version_ge(version, "22.04"):
        supported = True
    if distro_id == "debian" and version and _version_ge(version, "12"):
        supported = True
    if supported:
        return CheckResult("Operating system", "PASS", pretty)
    return CheckResult(
        "Operating system",
        "FAIL",
        f"Unsupported operating system: {pretty}. {SUPPORTED_OS_MESSAGE}",
    )


def check_architecture() -> CheckResult:
    machine = platform.machine().lower()
    mapping = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    arch = mapping.get(machine)
    if arch:
        return CheckResult("Architecture", "PASS", arch)
    return CheckResult(
        "Architecture",
        "FAIL",
        f"Unsupported architecture: {machine}. Use amd64 or arm64.",
    )


def check_cpu() -> CheckResult:
    count = os.cpu_count() or 0
    if count >= 2:
        return CheckResult("CPU", "PASS", f"{count} cores")
    if count >= 1:
        return CheckResult("CPU", "WARN", f"{count} core. 2 cores recommended.")
    return CheckResult("CPU", "FAIL", "Unable to detect CPU cores")


def _memory_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                parts = line.split()
                return int(parts[1]) * 1024
    if platform.system() == "Darwin":
        result = _run(["sysctl", "-n", "hw.memsize"])
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())
    return None


def check_memory() -> CheckResult:
    total = _memory_bytes()
    if total is None:
        return CheckResult("Memory", "WARN", "Unable to detect memory")
    gib = total / (1024**3)
    label = f"{gib:.1f} GB"
    if gib >= 2:
        return CheckResult("Memory", "PASS", label)
    if gib >= 0.5:
        return CheckResult("Memory", "WARN", f"{label}. 2 GB recommended.")
    return CheckResult("Memory", "FAIL", f"{label} is below the minimum usable amount")


def check_disk() -> CheckResult:
    usage = shutil.disk_usage(str(Path.home()))
    free_gb = usage.free / (1024**3)
    label = f"{free_gb:.1f} GB free"
    if free_gb >= 10:
        return CheckResult("Disk", "PASS", label)
    if free_gb >= 2:
        return CheckResult("Disk", "WARN", f"{label}. 10 GB recommended.")
    return CheckResult("Disk", "FAIL", f"{label} is too low")


def check_command(name: str, command: str, missing: Status = "FAIL") -> CheckResult:
    path = _which(command)
    if path:
        return CheckResult(name, "PASS", path)
    return CheckResult(name, missing, f"{command} is not installed")


def check_nginx() -> CheckResult:
    path = _which("nginx")
    if not path:
        return CheckResult("Nginx", "WARN", "nginx is not installed")
    result = _run(["nginx", "-t"])
    if result.returncode == 0:
        return CheckResult("Nginx", "PASS", "nginx configuration is valid")
    detail = (result.stderr or result.stdout).strip().splitlines()
    message = detail[-1] if detail else "nginx -t failed"
    return CheckResult("Nginx", "FAIL", message)


def check_systemd() -> CheckResult:
    if Path("/run/systemd/system").exists() or _which("systemctl"):
        if Path("/run/systemd/system").exists():
            return CheckResult("systemd", "PASS", "systemd is available")
        return CheckResult(
            "systemd",
            "WARN",
            "systemctl exists but systemd is not the running init",
        )
    return CheckResult("systemd", "WARN", "systemd is not available on this machine")


def check_firewall() -> CheckResult:
    ufw = _which("ufw")
    if not ufw:
        return CheckResult(
            "Firewall",
            "WARN",
            "ufw is not installed. Public ports should be 22, 80, and 443.",
        )
    result = _run(["ufw", "status"])
    output = (result.stdout or "").strip()
    if "Status: inactive" in output:
        return CheckResult(
            "Firewall",
            "WARN",
            "ufw is inactive. SSH, HTTP, and HTTPS should remain reachable.",
        )
    if result.returncode != 0:
        return CheckResult("Firewall", "WARN", "Unable to read ufw status without mutating rules")
    return CheckResult("Firewall", "PASS", "ufw is present. Existing rules were not changed.")


def check_service(settings: Settings) -> CheckResult:
    if Path("/run/systemd/system").exists():
        result = _run(["systemctl", "is-active", "vps-deployer"])
        if result.returncode == 0 and result.stdout.strip() == "active":
            return CheckResult("VPS Deployer service", "PASS", "vps-deployer.service is active")
        return CheckResult("VPS Deployer service", "WARN", "vps-deployer.service is not active")
    try:
        import httpx

        response = httpx.get(f"{settings.api_base_url}/health", timeout=1.0)
        if response.status_code == 200:
            return CheckResult(
                "VPS Deployer service",
                "PASS",
                f"API is healthy at {settings.api_base_url}",
            )
    except Exception:
        pass
    return CheckResult(
        "VPS Deployer service",
        "WARN",
        f"API is not reachable at {settings.api_base_url}. Start it for local development.",
    )


def check_database(settings: Settings) -> CheckResult:
    try:
        from vps_deployer.db.session import get_engine, init_db

        init_db(settings)
        engine = get_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return CheckResult("Database", "PASS", str(settings.database_path))
    except Exception as exc:
        return CheckResult("Database", "FAIL", f"Database is not healthy: {exc}")


def check_github(settings: Settings) -> CheckResult:
    from vps_deployer.core.github import is_github_configured

    if is_github_configured(settings):
        return CheckResult("GitHub", "PASS", "GitHub App files are present")
    return CheckResult("GitHub", "WARN", "GitHub is not configured")


def run_doctor(settings: Settings | None = None) -> list[CheckResult]:
    current = settings or get_settings()
    current.ensure_directories()
    return [
        check_operating_system(),
        check_architecture(),
        check_cpu(),
        check_memory(),
        check_disk(),
        check_command("Git", "git"),
        check_command("Python", "python3"),
        check_command("uv", "uv", missing="WARN"),
        check_command("Node.js", "node", missing="WARN"),
        check_command("npm", "npm", missing="WARN"),
        check_nginx(),
        check_systemd(),
        check_firewall(),
        check_service(current),
        check_database(current),
        check_github(current),
    ]


def doctor_payload(settings: Settings | None = None) -> dict[str, object]:
    checks = run_doctor(settings)
    summary = {
        "pass": sum(1 for item in checks if item.status == "PASS"),
        "warn": sum(1 for item in checks if item.status == "WARN"),
        "fail": sum(1 for item in checks if item.status == "FAIL"),
    }
    return {
        "ok": summary["fail"] == 0,
        "version": get_version(),
        "summary": summary,
        "checks": [asdict(item) for item in checks],
    }
