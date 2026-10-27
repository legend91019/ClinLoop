"""Add patient clinical document drafts.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinical_documents",
        sa.Column("document_id", sa.String(64), primary_key=True),
        sa.Column(
            "patient_id", sa.String(64), sa.ForeignKey("patients.patient_id"), nullable=False
        ),
        sa.Column(
            "encounter_id", sa.String(64), sa.ForeignKey("encounters.encounter_id"), nullable=False
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("event_id", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_documents_patient_encounter", "clinical_documents", ["patient_id", "encounter_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_documents_patient_encounter", table_name="clinical_documents")
    op.drop_table("clinical_documents")
