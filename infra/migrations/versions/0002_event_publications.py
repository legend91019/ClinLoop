"""Add transactional event publication outbox.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_publications",
        sa.Column(
            "event_id",
            sa.String(64),
            sa.ForeignKey("clinical_events.event_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_event_publications_pending", "event_publications", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_event_publications_pending", table_name="event_publications")
    op.drop_table("event_publications")
