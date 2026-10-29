"""Prepare the complete synthetic local product demo without deleting existing data."""

from __future__ import annotations

import argparse

from apps.api.app.db import build_engine, session_scope
from apps.api.app.settings import get_settings
from packages.fixtures.patient_workspace import seed_workspace_patients
from scripts.init_local_trial import init_local_trial


def init_product_demo(database_url: str) -> int:
    """Create the legacy event case and six patient workspaces; return newly added workspaces."""
    init_local_trial(database_url)
    engine = build_engine(database_url)
    try:
        with session_scope(engine) as session:
            return seed_workspace_patients(session)
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args()
    created = init_product_demo(args.database_url)
    print(f"Local product demo ready: P-1001 plus six patient workspaces ({created} added).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
