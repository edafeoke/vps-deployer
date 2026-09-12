from __future__ import annotations

from pathlib import Path

from vps_deployer.core.config import PRODUCTION_CONFIG_DIR, _settings_env_file


def test_settings_env_file_ignores_unreadable_production_config(monkeypatch) -> None:
    monkeypatch.delenv("VPS_DEPLOYER_ENV_FILE", raising=False)
    original = Path.is_file

    def guarded(self: Path) -> bool:
        if self == PRODUCTION_CONFIG_DIR / "config.env":
            raise PermissionError("denied")
        return original(self)

    monkeypatch.setattr(Path, "is_file", guarded)
    assert _settings_env_file() != PRODUCTION_CONFIG_DIR / "config.env"


def test_production_layout_available_ignores_unreadable_dir(monkeypatch) -> None:
    from vps_deployer.core.config import production_layout_available

    original = Path.is_dir

    def guarded(self: Path) -> bool:
        if self == PRODUCTION_CONFIG_DIR:
            raise PermissionError("denied")
        return original(self)

    monkeypatch.setattr(Path, "is_dir", guarded)
    assert production_layout_available() is False
