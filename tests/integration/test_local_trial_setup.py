from __future__ import annotations

from apps.api.app.db import build_engine, session_scope
from apps.api.app.db_models import Encounter, Patient
from scripts.init_local_trial import init_local_trial


def test_local_trial_setup_creates_only_demographics(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'trial.sqlite3'}"
    init_local_trial(url)
    engine = build_engine(url)
    try:
        with session_scope(engine) as session:
            assert session.get(Patient, "P-1001") is not None
            assert session.get(Encounter, "ENC-2001") is not None
            from apps.api.app.repositories import ClinicalEventRepository, LoopRepository

            assert ClinicalEventRepository(session).list_for_patient("P-1001") == []
            assert LoopRepository(session).list_for_patient("P-1001") == []
    finally:
        engine.dispose()
