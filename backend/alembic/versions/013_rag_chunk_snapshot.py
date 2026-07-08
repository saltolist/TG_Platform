"""RAG chunk snapshot columns for Tier A escalation signals

Revision ID: 013_rag_chunk_snapshot
Revises: 012_agentic_rag_node_types
Create Date: 2026-07-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_rag_chunk_snapshot"
down_revision: Union[str, None] = "012_agentic_rag_node_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "note_embeddings",
        sa.Column("chunk_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "note_embeddings",
        sa.Column(
            "referenced_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("note_embeddings", "referenced_ids")
    op.drop_column("note_embeddings", "chunk_text")
