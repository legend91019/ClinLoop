"""Prepare an empty SQLite case for the live Agent trial."""

from __future__ import annotations

import argparse

from apps.api.app.db import build_engine, create_schema, session_scope
from apps.api.app.repositories import PatientRepository
from apps.api.app.settings import get_settings


def init_local_trial(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        raise ValueError("local trial requires a SQLite DATABASE_URL")
    engine = build_engine(database_url)
    try:
        create_schema(engine)
        with session_scope(engine) as session:
            PatientRepository(session).ensure(
                patient_id="P-1001",
                encounter_id="ENC-2001",
                display_name="合成患者 P-1001",
                ward="Demo",
            )
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args()
    init_local_trial(args.database_url)
    print("Local synthetic case ready: P-1001 / ENC-2001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
