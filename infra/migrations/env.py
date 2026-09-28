"""Alembic environment.

The database URL always comes from ``DATABASE_URL`` (via
:func:`apps.api.app.db.database_url`), never from ``alembic.ini`` — that
keeps credentials out of a tracked file.

Usage::

    alembic upgrade head
    alembic downgrade base
    alembic revision --autogenerate -m "..."   # requires a live database
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Engine, pool

from apps.api.app import db as db_module
from apps.api.app import db_models  # noqa: F401  (registers every table)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = db_module.Base.metadata


def get_url() -> str:
    """Resolve the migration target URL."""
    return db_module.database_url()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    engine: Engine = db_module.build_engine(get_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER most columns; batch mode rewrites the table.
            render_as_batch=not db_module.is_postgres(get_url()),
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()


# Keep a reference so linters do not flag the import as unused when the
# offline path is taken.
_ = pool
