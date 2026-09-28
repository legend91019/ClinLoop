"""Database engine, session and schema helpers.

``DATABASE_URL`` is the single source of truth. PostgreSQL 16 is the
target runtime (``postgresql+psycopg://...``); SQLite is accepted so the
foundation suite can run without Docker, and the seed/API work unchanged
on both.

Nothing here ever falls back to a hard-coded credential — a missing or
blank URL raises immediately.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

__all__ = [
    "Base",
    "DEFAULT_DATABASE_URL",
    "build_engine",
    "session_factory",
    "get_session",
    "session_scope",
    "create_schema",
    "drop_schema",
    "database_url",
    "is_postgres",
]

#: Development default. Matches ``.env.example`` and ``docker-compose.yml``.
DEFAULT_DATABASE_URL = "postgresql+psycopg://clinloop:clinloop@localhost:5432/clinloop"


class Base(DeclarativeBase):
    """Declarative base for every ClinLoop table."""


def database_url(explicit: str | None = None) -> str:
    """Resolve the database URL, preferring an explicit argument."""
    url = explicit or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    if not url.strip():
        raise RuntimeError(
            "DATABASE_URL is empty. Copy .env.example to .env and set a value "
            "(never commit the real one)."
        )
    return url.strip()


def is_postgres(url: str) -> bool:
    """True when ``url`` targets PostgreSQL."""
    return url.startswith("postgresql")


def build_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create an :class:`Engine` for ``url``.

    SQLite needs ``check_same_thread=False`` plus foreign-key enforcement
    so that tests observe the same referential rules as PostgreSQL.
    """
    resolved = database_url(url)

    if resolved.startswith("sqlite"):
        from sqlalchemy import event

        engine = create_engine(
            resolved,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    return create_engine(resolved, echo=echo, future=True, pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a session and always close it.

    The engine is created lazily and cached on the module so tests can
    point ``DATABASE_URL`` at SQLite without re-importing.
    """
    engine = _shared_engine()
    factory = session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional scope for scripts (seed, migrations, demo runner)."""
    eng = engine or _shared_engine()
    factory = session_factory(eng)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_SHARED_ENGINE: Engine | None = None


def _shared_engine() -> Engine:
    """Process-wide lazily-created engine."""
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        _SHARED_ENGINE = build_engine()
    return _SHARED_ENGINE


def reset_shared_engine() -> None:
    """Drop the cached engine. Used by tests when DATABASE_URL changes."""
    global _SHARED_ENGINE
    if _SHARED_ENGINE is not None:
        _SHARED_ENGINE.dispose()
    _SHARED_ENGINE = None


def create_schema(engine: Engine) -> None:
    """Create every table from metadata. Used by tests and ``make dev``."""
    Base.metadata.create_all(engine)


def drop_schema(engine: Engine) -> None:
    """Drop every table from metadata. Never call this against real data."""
    Base.metadata.drop_all(engine)


def sqlite_path_from_url(url: str) -> Path | None:
    """Extract the filesystem path from a SQLite URL, if any."""
    prefix = "sqlite+pysqlite:///"
    if not url.startswith(prefix):
        return None
    return Path(url[len(prefix) :])
