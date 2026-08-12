"""Durable agent batch jobs.

Revision ID: 022_agent_batch_scale
Revises: 021_discovery_keywords
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "022_agent_batch_scale"
down_revision: Union[str, None] = "021_discovery_keywords"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_batch_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="global"),
        sa.Column("query", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("page_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_items", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("max_db_calls", sa.Integer(), nullable=False, server_default="128"),
        sa.Column("max_llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cursor", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "checkpoint",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer(), nullable=True),
        sa.Column("db_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("celery_task_id", sa.String(128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_batch_jobs_user_status",
        "agent_batch_jobs",
        ["user_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_agent_batch_jobs_queue",
        "agent_batch_jobs",
        ["status", "updated_at"],
    )

    op.create_table(
        "agent_batch_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_batch_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("object_kind", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "job_id", "object_kind", "source_id", name="uq_agent_batch_items_source"
        ),
    )
    op.create_index(
        "ix_agent_batch_items_page", "agent_batch_items", ["job_id", "sequence"]
    )

def downgrade() -> None:
    op.drop_index("ix_agent_batch_items_page", table_name="agent_batch_items")
    op.drop_table("agent_batch_items")
    op.drop_index("ix_agent_batch_jobs_queue", table_name="agent_batch_jobs")
    op.drop_index("ix_agent_batch_jobs_user_status", table_name="agent_batch_jobs")
    op.drop_table("agent_batch_jobs")
