"""Durable care assistance runs.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "care_assistance",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("encounter_id", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("document_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_care_assistance_scope", "care_assistance", ["patient_id", "encounter_id"])


def downgrade():
    op.drop_table("care_assistance")
