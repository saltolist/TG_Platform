"""Persist model-independent semantic flags beside Selector cards.

Revision ID: 028_selector_semantic_flags
Revises: 027_agent_run_answer_llm
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "028_selector_semantic_flags"
down_revision: Union[str, None] = "027_agent_run_answer_llm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "note_embeddings",
        sa.Column(
            "selector_semantic_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("note_embeddings", "selector_semantic_flags")
