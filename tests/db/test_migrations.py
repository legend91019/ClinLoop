"""Migration tests (Task 3).

Verifies that the Alembic revision actually builds the schema, rather
than trusting ``Base.metadata`` — those two can drift.

Runs against ``CLINLOOP_TEST_DATABASE_URL`` when set (CI: PostgreSQL 16),
otherwise a scratch SQLite file.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from apps.api.app.db import build_engine

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Tables the initial revision must create, in dependency order.
EXPECTED_TABLES = {
    "patients",
    "encounters",
    "clinical_events",
    "clinical_intents",
    "open_loops",
    "evidence_nodes",
    "findings",
    "agent_runs",
    "review_decisions",
    "handoff_reports",
    "audit_logs",
}


def _alembic_config(url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "infra" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def migration_url() -> Iterator[str]:
    override = os.environ.get("CLINLOOP_TEST_DATABASE_URL")
    if override:
        return override
    # Scratch files live in the repo (gitignored) rather than the system
    # temp directory, which is not writable in every sandbox.
    scratch = REPO_ROOT / f".pytest-migration-{uuid.uuid4().hex[:8]}.sqlite3"
    url = f"sqlite+pysqlite:///{scratch.as_posix()}"
    try:
        yield url
    finally:
        scratch.unlink(missing_ok=True)


@pytest.fixture
def migrated_engine(migration_url: str):  # type: ignore[no-untyped-def]
    os.environ["DATABASE_URL"] = migration_url
    from apps.api.app import db as db_module

    db_module.reset_shared_engine()

    config = _alembic_config(migration_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = build_engine(migration_url)
    try:
        yield engine
    finally:
        engine.dispose()
        db_module.reset_shared_engine()


def test_upgrade_head_creates_every_core_table(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    present = set(inspect(migrated_engine).get_table_names())
    assert EXPECTED_TABLES <= present, f"missing: {sorted(EXPECTED_TABLES - present)}"


def test_migration_and_metadata_agree(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """Hand-written DDL must match the ORM metadata exactly."""
    from apps.api.app import db_models  # noqa: F401
    from apps.api.app.db import Base

    migrated = {t for t in inspect(migrated_engine).get_table_names() if t in EXPECTED_TABLES}
    declared = set(Base.metadata.tables)
    assert migrated == declared & EXPECTED_TABLES, (
        "migration/metadata drift: "
        f"only in migration={sorted(migrated - declared)}, "
        f"only in metadata={sorted((declared & EXPECTED_TABLES) - migrated)}"
    )


def test_core_tables_have_timestamps_and_payload(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    inspector = inspect(migrated_engine)
    for table in sorted(EXPECTED_TABLES):
        columns = {c["name"] for c in inspector.get_columns(table)}
        assert {"created_at", "updated_at", "payload"} <= columns, (
            f"{table} is missing auditability columns: "
            f"{sorted({'created_at', 'updated_at', 'payload'} - columns)}"
        )


def test_expected_indexes_exist(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    inspector = inspect(migrated_engine)
    names = {index["name"] for table in EXPECTED_TABLES for index in inspector.get_indexes(table)}
    for required in (
        "ix_clinical_events_patient_event_time",
        "ix_open_loops_patient_state",
        "ix_evidence_nodes_loop_observed_at",
        "ix_audit_logs_entity_time",
    ):
        assert required in names, f"missing index: {required}"


def test_downgrade_base_removes_everything(migration_url: str) -> None:
    os.environ["DATABASE_URL"] = migration_url
    from apps.api.app import db as db_module

    db_module.reset_shared_engine()

    config = _alembic_config(migration_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(migration_url)
    try:
        remaining = set(inspect(engine).get_table_names()) & EXPECTED_TABLES
        assert remaining == set(), f"downgrade left tables behind: {sorted(remaining)}"
    finally:
        engine.dispose()
        db_module.reset_shared_engine()


def test_migration_is_repeatable_in_both_directions(migration_url: str) -> None:
    """upgrade -> downgrade -> upgrade must be stable (the reset-db path)."""
    os.environ["DATABASE_URL"] = migration_url
    from apps.api.app import db as db_module

    db_module.reset_shared_engine()

    config = _alembic_config(migration_url)
    for _ in range(2):
        command.upgrade(config, "head")
        engine = build_engine(migration_url)
        try:
            assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        command.downgrade(config, "base")

    db_module.reset_shared_engine()
