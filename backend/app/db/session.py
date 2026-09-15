"""Database engine and request-scoped sessions.

Provider-neutral: the same code runs against local SQLite, Docker PostgreSQL and a managed
PostgreSQL such as Neon. Connection details come only from DATABASE_URL (and optionally
MIGRATION_DATABASE_URL for a direct, unpooled migration connection), never from hard-coded
hostnames. Connection strings are never logged.

Pool sizes are deliberately small: several processes (API, worker, migration job, scheduled
purge) share one managed database with a limited connection budget.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.db.urls import connect_args, normalise_database_url

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _connect_args(settings: Settings, url: str, *, application_name: str | None = None) -> dict:
    return connect_args(
        url,
        sslmode=settings.db_sslmode.strip().lower(),
        connect_timeout=settings.db_connect_timeout_seconds,
        application_name=settings.db_application_name if application_name is None else application_name,
    )


def create_db_engine(settings: Settings | None = None, *, url: str | None = None) -> Engine:
    settings = settings or get_settings()
    target = normalise_database_url(url or settings.database_url)
    if target.startswith("sqlite"):
        return create_engine(
            target,
            future=True,
            pool_pre_ping=True,
            connect_args=_connect_args(settings, target),
        )
    return create_engine(
        target,
        future=True,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args=_connect_args(settings, target),
    )


def migration_url(settings: Settings | None = None) -> str:
    """Direct (unpooled) URL for migrations when the runtime URL is a pooled endpoint."""
    settings = settings or get_settings()
    return normalise_database_url(settings.migration_database_url or settings.database_url)


def create_migration_engine(settings: Settings | None = None) -> Engine:
    """Alembic's online engine: the migration URL, the same TLS/timeout arguments, no pool."""
    settings = settings or get_settings()
    target = migration_url(settings)
    name = f"{settings.db_application_name}-migrations" if settings.db_application_name else ""
    return create_engine(
        target,
        future=True,
        poolclass=NullPool,
        connect_args=_connect_args(settings, target, application_name=name),
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
