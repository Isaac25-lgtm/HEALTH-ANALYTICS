from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.db.base import Base
from app.models import *  # noqa: F401,F403

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _apply_url() -> None:
    # Prefer MIGRATION_DATABASE_URL: a pooled endpoint (Neon) is not always suitable for DDL.
    from app.db.session import migration_url

    config.set_main_option("sqlalchemy.url", migration_url(get_settings()).replace("%", "%%"))


def run_migrations_offline() -> None:
    _apply_url()
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The same URL normalisation, TLS mode, connect timeout and application name as the runtime,
    # with NullPool so a release command never holds idle connections.
    from app.db.session import create_migration_engine

    connectable = create_migration_engine(get_settings())
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
