"""channel metric snapshots for real analytics history

Revision ID: 010_channel_metric_snapshots
Revises: 009_ai_model_usage_events
Create Date: 2026-07-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_channel_metric_snapshots"
down_revision: Union[str, None] = "009_ai_model_usage_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_metric_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subscribers", sa.Integer(), nullable=True),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reposts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("posts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("er", sa.Numeric(5, 1), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "captured_at", name="uq_channel_metric_snapshots_slot"),
    )
    op.create_index(
        "ix_channel_metric_snapshots_user_captured",
        "channel_metric_snapshots",
        ["user_id", sa.text("captured_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_metric_snapshots_user_captured", table_name="channel_metric_snapshots"
    )
    op.drop_table("channel_metric_snapshots")
