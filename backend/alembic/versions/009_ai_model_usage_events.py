"""ai model usage events for platform analytics

Revision ID: 009_ai_model_usage_events
Revises: 008_tenant_overlay_rag
Create Date: 2026-06-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_ai_model_usage_events"
down_revision: Union[str, None] = "008_tenant_overlay_rag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_model_usage_events",
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
        sa.Column("model_profile_id", sa.Text(), nullable=False),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False, server_default="global"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("is_stub", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ai_model_usage_events_user_created",
        "ai_model_usage_events",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_ai_model_usage_events_user_model",
        "ai_model_usage_events",
        ["user_id", "model_profile_id", "model_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_model_usage_events_user_model", table_name="ai_model_usage_events")
    op.drop_index("ix_ai_model_usage_events_user_created", table_name="ai_model_usage_events")
    op.drop_table("ai_model_usage_events")
