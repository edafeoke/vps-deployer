from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_lib() -> None:
    script = ROOT / "tests" / "installer" / "run_lib_tests.sh"
    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All installer library tests passed." in result.stdout


def test_installer_runs_uv_outside_invoker_home() -> None:
    text = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
    assert "run_uv_as_app_user" in text
    assert "UV_NO_CONFIG=1" in text
    assert "cd /opt/vps-deployer/app" in text
