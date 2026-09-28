"""Shared TestClient fixtures.

The API is exercised against a scratch SQLite database seeded with the
synthetic demo case. CI points ``CLINLOOP_TEST_DATABASE_URL`` at
PostgreSQL 16 so the same tests cover both engines.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from apps.api.app import db as db_module
from apps.api.app.testing import create_schema, drop_schema
from packages.fixtures import MAIN_PATIENT_ID, seed_demo_case

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def api_database_url() -> str:
    override = os.environ.get("CLINLOOP_TEST_DATABASE_URL")
    if override:
        return override
    scratch = REPO_ROOT / f".pytest-api-{uuid.uuid4().hex[:8]}.sqlite3"
    return f"sqlite+pysqlite:///{scratch.as_posix()}"


@pytest.fixture(scope="session")
def api_engine(api_database_url: str) -> Iterator[Engine]:
    os.environ["DATABASE_URL"] = api_database_url
    db_module.reset_shared_engine()

    engine = db_module.build_engine(api_database_url)
    drop_schema(engine)
    create_schema(engine)
    with db_module.session_factory(engine)() as session:
        seed_demo_case(session)
        session.commit()

    yield engine

    drop_schema(engine)
    engine.dispose()
    db_module.reset_shared_engine()

    if api_database_url.startswith("sqlite"):
        path = Path(api_database_url.split("///", 1)[1])
        path.unlink(missing_ok=True)


@pytest.fixture
def client(api_engine: Engine) -> Iterator[TestClient]:
    """A TestClient bound to the seeded database."""
    from apps.api.app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def patient_id() -> str:
    return MAIN_PATIENT_ID
