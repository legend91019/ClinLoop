"""Create additive local schema and six fictional patient workspaces."""

from apps.api.app.db import build_engine, create_schema, session_scope
from apps.api.app.settings import get_settings
from packages.fixtures.patient_workspace import seed_workspace_patients


def main() -> None:
    engine = build_engine(get_settings().database_url)
    try:
        create_schema(engine)
        with session_scope(engine) as session:
            created = seed_workspace_patients(session)
        print(
            f"Patient workspace ready: {created} fictional patients added; existing records preserved."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
