from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def create_db_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=_connect_args(settings.database_url),
    )


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_db_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def mark_writable(session: Session) -> Session:
    session.info["writable"] = True
    return session


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    session.info["writable"] = False
    try:
        yield session
        if session.info.get("writable"):
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_write_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    session.info["writable"] = True
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
