from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SITE_URL = "https://vps-deployer.onebitstack.com"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 5100

PRODUCTION_CONFIG_DIR = Path("/etc/vps-deployer")
PRODUCTION_DATA_DIR = Path("/var/lib/vps-deployer")
PRODUCTION_LOG_DIR = Path("/var/log/vps-deployer")


def find_repo_root(start: Path | None = None) -> Path | None:
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        if 'name = "vps-deployer"' in pyproject.read_text(encoding="utf-8"):
            return candidate
    return None


def production_layout_available() -> bool:
    return PRODUCTION_CONFIG_DIR.is_dir()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VPS_DEPLOYER_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    site_url: str = DEFAULT_SITE_URL
    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    config_dir: Path | None = None
    data_dir: Path | None = None
    log_dir: Path | None = None
    database_path: Path | None = None
    create_tables: bool = True

    def model_post_init(self, __context: object) -> None:
        layout = self._layout()
        if self.config_dir is None:
            self.config_dir = layout["config_dir"]
        if self.data_dir is None:
            self.data_dir = layout["data_dir"]
        if self.log_dir is None:
            self.log_dir = layout["log_dir"]
        if self.database_path is None:
            self.database_path = self.data_dir / "vps-deployer.db"

    def _layout(self) -> dict[str, Path]:
        if production_layout_available() and self.config_dir is None:
            return {
                "config_dir": PRODUCTION_CONFIG_DIR,
                "data_dir": PRODUCTION_DATA_DIR,
                "log_dir": PRODUCTION_LOG_DIR,
            }
        repo = find_repo_root()
        if repo is not None:
            base = repo / ".local"
        else:
            base = Path.home() / ".local" / "share" / "vps-deployer"
        return {
            "config_dir": base / "config",
            "data_dir": base / "data",
            "log_dir": base / "logs",
        }

    def ensure_directories(self) -> None:
        assert self.config_dir is not None
        assert self.data_dir is not None
        assert self.log_dir is not None
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def api_base_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"

    @property
    def database_url(self) -> str:
        assert self.database_path is not None
        return f"sqlite:///{self.database_path}"


def _settings_env_file() -> Path | None:
    if os.environ.get("VPS_DEPLOYER_ENV_FILE"):
        return Path(os.environ["VPS_DEPLOYER_ENV_FILE"])
    if (PRODUCTION_CONFIG_DIR / "config.env").is_file():
        return PRODUCTION_CONFIG_DIR / "config.env"
    repo = find_repo_root()
    if repo is not None:
        local = repo / ".local" / "config.env"
        if local.is_file():
            return local
    return None


@lru_cache
def get_settings() -> Settings:
    env_file = _settings_env_file()
    if env_file is not None:
        return Settings(_env_file=env_file, _env_file_encoding="utf-8")
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
