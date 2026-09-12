from __future__ import annotations

import subprocess
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "packaging" / "helper" / "vps-deployer-helper"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HELPER), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_helper_rejects_unknown_action() -> None:
    result = _run("rm")
    assert result.returncode == 2
    assert "rejected" in result.stderr


def test_helper_rejects_invalid_service_name() -> None:
    result = _run("service-status", "../etc/passwd")
    assert result.returncode == 2
    result = _run("service-status", "unit;reboot")
    assert result.returncode == 2
    result = _run("service-status", "unit$(id)")
    assert result.returncode == 2


def test_helper_missing_action() -> None:
    result = _run()
    assert result.returncode == 1
    assert "Usage" in result.stdout
