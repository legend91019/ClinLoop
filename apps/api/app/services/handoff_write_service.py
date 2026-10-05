"""Optimistic draft writes on SQLite and PostgreSQL, including sealed-state protection."""

from datetime import timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from apps.api.app.db_models import HandoffReportRow
from apps.api.app.db_time import as_utc
from packages.contracts import HandoffStatus, utcnow


def update_current_draft(session: Session, row: HandoffReportRow, values: dict[str, Any]) -> None:
    # SQLite ignores FOR UPDATE. Compare both status and the version read by the caller:
    # a concurrent edit or seal must not overwrite content or produce a false audit trail.
    result = session.execute(
        update(HandoffReportRow)
        .where(
            HandoffReportRow.handoff_id == row.handoff_id,
            HandoffReportRow.status == HandoffStatus.DRAFT.value,
            HandoffReportRow.updated_at == row.updated_at,
        )
        .values(
            **values,
            updated_at=max(utcnow(), as_utc(row.updated_at) + timedelta(microseconds=1)),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ValueError("handoff changed concurrently; reload before editing or sealing")
    session.refresh(row)
