"""Add timezone to agent_runs (schedule_post relative-time resolution)

Revision ID: 017_agent_run_timezone
Revises: 016_agent_run_post_chat_id
Create Date: 2026-07-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_agent_run_timezone"
down_revision: Union[str, None] = "016_agent_run_post_chat_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "timezone")
