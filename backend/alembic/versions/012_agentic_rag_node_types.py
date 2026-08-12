"""agentic RAG node types on embeddings + attachment_extractions cache

Revision ID: 012_agentic_rag_node_types
Revises: 011_post_metric_snapshots
Create Date: 2026-07-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_agentic_rag_node_types"
down_revision: Union[str, None] = "011_post_metric_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "note_embeddings",
        sa.Column("node_type", sa.Text(), nullable=False, server_default="note_chunk"),
    )
    op.add_column(
        "note_embeddings",
        sa.Column("file_id", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_constraint("uq_note_embeddings_note_chunk_model", "note_embeddings", type_="unique")
    op.create_unique_constraint(
        "uq_note_embeddings_node_chunk_model",
        "note_embeddings",
        ["user_id", "tenant_key", "scope", "node_type", "note_id", "file_id", "chunk_index", "model_key"],
    )
    op.create_index(
        "ix_note_embeddings_parent_files",
        "note_embeddings",
        ["user_id", "tenant_key", "scope", "note_id", "node_type"],
    )

    op.add_column(
        "embedding_jobs",
        sa.Column("node_type", sa.Text(), nullable=False, server_default="note_chunk"),
    )
    op.add_column(
        "embedding_jobs",
        sa.Column("file_id", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "attachment_extractions",
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
        sa.Column("tenant_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("note_id", sa.Text(), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "tenant_key",
            "scope",
            "note_id",
            "file_id",
            name="uq_attachment_extractions",
        ),
    )


def downgrade() -> None:
    op.drop_table("attachment_extractions")

    op.drop_column("embedding_jobs", "file_id")
    op.drop_column("embedding_jobs", "node_type")

    op.drop_index("ix_note_embeddings_parent_files", table_name="note_embeddings")
    op.drop_constraint("uq_note_embeddings_node_chunk_model", "note_embeddings", type_="unique")
    op.create_unique_constraint(
        "uq_note_embeddings_note_chunk_model",
        "note_embeddings",
        ["user_id", "tenant_key", "scope", "note_id", "chunk_index", "model_key"],
    )
    op.drop_column("note_embeddings", "file_id")
    op.drop_column("note_embeddings", "node_type")
