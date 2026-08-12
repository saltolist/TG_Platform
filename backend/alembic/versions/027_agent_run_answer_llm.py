"""Persist the composer-selected answer model on agent runs.

Revision ID: 027_agent_run_answer_llm
Revises: 026_selector_summary_projection
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027_agent_run_answer_llm"
down_revision: Union[str, None] = "026_selector_summary_projection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("answer_llm_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "answer_llm_id")
