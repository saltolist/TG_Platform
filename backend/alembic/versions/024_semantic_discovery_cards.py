"""Version semantic discovery cards.

Revision ID: 024_semantic_discovery_cards
Revises: 023_retrieval_scale_indexes
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_semantic_discovery_cards"
down_revision: Union[str, None] = "023_retrieval_scale_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "note_embeddings",
        sa.Column("summary_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "note_embeddings",
        sa.Column("summary_model", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("note_embeddings", "summary_model")
    op.drop_column("note_embeddings", "summary_version")
