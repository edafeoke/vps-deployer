from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from vps_deployer.core.config import Settings, get_settings

_engine: Engine | None = None


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    current = settings or get_settings()
    current.ensure_directories()
    url = current.database_url
    if _engine is None or str(_engine.url) != url:
        _engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db(settings: Settings | None = None) -> None:
    current = settings or get_settings()
    engine = get_engine(current)
    if current.create_tables:
        import vps_deployer.db.models  # noqa: F401

        SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
