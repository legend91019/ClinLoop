"""A fresh local product demo starts with the patient directory and stays idempotent."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db import build_engine
from apps.api.app.db_models import ClinicalDocumentRow, Patient
from scripts.init_product_demo import init_product_demo


def test_product_demo_init_is_repeatable(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'product.sqlite3').as_posix()}"
    assert init_product_demo(url) == 6
    assert init_product_demo(url) == 0

    engine = build_engine(url)
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Patient)) == 7
            assert session.scalar(select(func.count()).select_from(ClinicalDocumentRow)) == 12
            assert session.get(Patient, "P-1001") is not None
            assert session.get(Patient, "P-2001") is not None
    finally:
        engine.dispose()
