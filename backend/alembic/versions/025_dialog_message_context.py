"""Add durable message context manifests.

Revision ID: 025_dialog_message_context
Revises: 024_semantic_discovery_cards
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025_dialog_message_context"
down_revision: Union[str, None] = "024_semantic_discovery_cards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "assistant_message_id",
            sa.String(length=128),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
    )
    op.create_unique_constraint(
        "uq_agent_runs_assistant_message_id", "agent_runs", ["assistant_message_id"]
    )
    op.alter_column("agent_runs", "assistant_message_id", server_default=None)

    op.create_table(
        "dialog_message_context",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ledger_key", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("manifest_schema", sa.String(length=128), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_revision_digest", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "ledger_key", "message_id",
            name="uq_dialog_message_context_owner_message",
        ),
        sa.UniqueConstraint("run_id", name="uq_dialog_message_context_run"),
    )
    op.create_index(
        op.f("ix_dialog_message_context_message_id"),
        "dialog_message_context", ["message_id"], unique=False,
    )
    op.create_index(
        op.f("ix_dialog_message_context_run_id"),
        "dialog_message_context", ["run_id"], unique=False,
    )
    op.create_index(
        op.f("ix_dialog_message_context_user_id"),
        "dialog_message_context", ["user_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dialog_message_context_user_id"), table_name="dialog_message_context")
    op.drop_index(op.f("ix_dialog_message_context_run_id"), table_name="dialog_message_context")
    op.drop_index(op.f("ix_dialog_message_context_message_id"), table_name="dialog_message_context")
    op.drop_table("dialog_message_context")
    op.drop_constraint("uq_agent_runs_assistant_message_id", "agent_runs", type_="unique")
    op.drop_column("agent_runs", "assistant_message_id")
