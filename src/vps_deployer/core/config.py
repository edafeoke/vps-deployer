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


def _path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _path_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def production_layout_available() -> bool:
    return _path_is_dir(PRODUCTION_CONFIG_DIR)


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
    apps_root: Path | None = None
    git_clone_base: Path | None = None
    create_tables: bool = True
    worker_enabled: bool = True
    release_retention: int = 5
    runtime: str = "auto"
    helper_path: Path | None = None
    helper_sudo: bool = True
    nginx_dir: Path | None = None
    ssl_dir: Path | None = None
    ssl_email: str | None = None

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
        if self.apps_root is None:
            if production_layout_available() and self.config_dir == PRODUCTION_CONFIG_DIR:
                self.apps_root = Path("/var/www/apps")
            else:
                repo = find_repo_root()
                self.apps_root = (repo / ".local" / "apps") if repo else Path("/var/www/apps")
        if self.nginx_dir is None and not (
            production_layout_available() and self.config_dir == PRODUCTION_CONFIG_DIR
        ):
            repo = find_repo_root()
            self.nginx_dir = (repo / ".local" / "nginx") if repo else None
        if self.ssl_dir is None and self.nginx_dir is not None:
            self.ssl_dir = self.nginx_dir / "certs"

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
        if self.apps_root is not None:
            self.apps_root.mkdir(parents=True, exist_ok=True)
        if self.nginx_dir is not None:
            self.nginx_dir.mkdir(parents=True, exist_ok=True)
        if self.ssl_dir is not None:
            self.ssl_dir.mkdir(parents=True, exist_ok=True)

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
    production_env = PRODUCTION_CONFIG_DIR / "config.env"
    if _path_is_file(production_env):
        return production_env
    repo = find_repo_root()
    if repo is not None:
        local = repo / ".local" / "config.env"
        if _path_is_file(local):
            return local
    return None


@lru_cache
def get_settings() -> Settings:
    env_file = _settings_env_file()
    if env_file is None:
        return Settings()
    try:
        return Settings(_env_file=env_file, _env_file_encoding="utf-8")
    except OSError:
        return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
