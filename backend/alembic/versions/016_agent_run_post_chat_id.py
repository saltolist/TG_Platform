"""Add post_chat_id to agent_runs (post-scope chat disambiguation)

Revision ID: 016_agent_run_post_chat_id
Revises: 015_agent_runtime
Create Date: 2026-07-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_agent_run_post_chat_id"
down_revision: Union[str, None] = "015_agent_runtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("post_chat_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "post_chat_id")
