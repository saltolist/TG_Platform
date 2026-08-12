"""per-post metric snapshots for channel analytics history

Revision ID: 011_post_metric_snapshots
Revises: 010_channel_metric_snapshots
Create Date: 2026-07-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_post_metric_snapshots"
down_revision: Union[str, None] = "010_channel_metric_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post_metric_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reposts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("post_id", "captured_at", name="uq_post_metric_snapshots_slot"),
    )
    op.create_index(
        "ix_post_metric_snapshots_post_captured",
        "post_metric_snapshots",
        ["post_id", sa.text("captured_at DESC")],
    )
    op.create_index(
        "ix_post_metric_snapshots_user_captured",
        "post_metric_snapshots",
        ["user_id", sa.text("captured_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_post_metric_snapshots_user_captured", table_name="post_metric_snapshots"
    )
    op.drop_index(
        "ix_post_metric_snapshots_post_captured", table_name="post_metric_snapshots"
    )
    op.drop_table("post_metric_snapshots")
