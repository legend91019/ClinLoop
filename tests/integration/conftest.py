from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from apps.api.app import db as db_module
from apps.api.app.testing import create_schema, drop_schema
from packages.fixtures import seed_demo_case


@pytest.fixture
def api_engine(tmp_path) -> Iterator[Engine]:
    url = f"sqlite+pysqlite:///{(tmp_path / 'integration.sqlite3').as_posix()}"
    engine = db_module.build_engine(url)
    drop_schema(engine)
    create_schema(engine)
    with db_module.session_factory(engine)() as session:
        seed_demo_case(session)
        session.commit()
    yield engine
    drop_schema(engine)
    engine.dispose()
