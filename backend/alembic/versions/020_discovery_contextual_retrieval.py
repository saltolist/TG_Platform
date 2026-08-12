"""Discovery metadata and contextual search text for phase 4 retrieval.

Revision ID: 020_discovery_context
Revises: 019_turn_contract_v2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_discovery_context"
down_revision: Union[str, None] = "019_turn_contract_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ``chunk_text`` remains the original source snapshot used for citations.
    # ``search_text`` is the contextualized representation used only for
    # lexical/vector discovery and can therefore be regenerated independently.
    op.add_column(
        "note_embeddings",
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "note_embeddings",
        sa.Column("object_title", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "note_embeddings",
        sa.Column("object_status", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "note_embeddings",
        sa.Column("index_revision", sa.BigInteger(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_note_embeddings_discovery",
        "note_embeddings",
        ["user_id", "tenant_key", "scope", "node_type", "object_status", "index_revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_note_embeddings_discovery", table_name="note_embeddings")
    op.drop_column("note_embeddings", "index_revision")
    op.drop_column("note_embeddings", "object_status")
    op.drop_column("note_embeddings", "object_title")
    op.drop_column("note_embeddings", "search_text")
