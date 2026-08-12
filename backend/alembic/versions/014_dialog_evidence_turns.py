"""Dialog evidence turns for ADR-009 ledger persistence

Revision ID: 014_dialog_evidence_turns
Revises: 013_rag_chunk_snapshot
Create Date: 2026-07-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_dialog_evidence_turns"
down_revision: Union[str, None] = "013_rag_chunk_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dialog_evidence_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ledger_key", sa.String(length=512), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_post_id", sa.String(length=128), nullable=True),
        sa.Column("target_evidence_gap", sa.String(length=64), nullable=True),
        sa.Column(
            "entities",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dialog_evidence_turns_user_ledger_recorded",
        "dialog_evidence_turns",
        ["user_id", "ledger_key", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dialog_evidence_turns_user_ledger_recorded",
        table_name="dialog_evidence_turns",
    )
    op.drop_table("dialog_evidence_turns")
