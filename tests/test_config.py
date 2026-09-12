from __future__ import annotations

from pathlib import Path

from vps_deployer.core.config import (
    PRODUCTION_CONFIG_DIR,
    _settings_env_file,
    get_settings,
    reset_settings,
)


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


def test_get_settings_ignores_unreadable_env_file(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "config.env"
    env_file.write_text("VPS_DEPLOYER_API_PORT=51999\n", encoding="utf-8")
    env_file.chmod(0o000)
    monkeypatch.setenv("VPS_DEPLOYER_ENV_FILE", str(env_file))
    reset_settings()
    try:
        settings = get_settings()
        assert settings.api_port == 5100
    finally:
        env_file.chmod(0o644)
        reset_settings()
