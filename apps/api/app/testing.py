"""Schema creation/drop helpers for tests and local development.

Kept separate from :mod:`apps.api.app.db` so that production code paths
never import test utilities, and vice versa.
"""

from __future__ import annotations

from sqlalchemy import Engine

from apps.api.app import db as _db

__all__ = ["create_schema", "drop_schema", "create_all", "drop_all"]


def create_schema(engine: Engine) -> None:
    """Create all tables defined on the shared metadata."""
    # Importing the models registers them on Base.metadata.
    from apps.api.app import db_models  # noqa: F401

    _db.Base.metadata.create_all(engine)


def drop_schema(engine: Engine) -> None:
    """Drop all tables defined on the shared metadata."""
    from apps.api.app import db_models  # noqa: F401

    _db.Base.metadata.drop_all(engine)


#: Aliases used by migration/seed scripts.
create_all = create_schema
drop_all = drop_schema
