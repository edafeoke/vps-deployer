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


def test_installer_config_dir_is_group_readable() -> None:
    text = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
    assert "chown root:vps-deployer /etc/vps-deployer" in text
    assert "chmod 640 /etc/vps-deployer/config.env" in text
    assert 'usermod -aG vps-deployer "$SUDO_USER"' in text
    assert "restore_previous_install" in text
    assert "snapshot_existing" in text
    assert "pre-install.staging" in text
    restore = text.split("restore_previous_install()")[1].split("run_uv_as_app_user")[0]
    assert "/var/www/apps" not in restore
