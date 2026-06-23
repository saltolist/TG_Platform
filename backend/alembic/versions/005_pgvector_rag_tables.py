"""add pgvector extension, note_embeddings and embedding_jobs tables

Revision ID: 005_pgvector_rag_tables
Revises: 004_notes_markdown_migration
Create Date: 2026-06-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_pgvector_rag_tables"
down_revision: Union[str, None] = "004_notes_markdown_migration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Attempt to enable pgvector extension.
    # We use a SAVEPOINT so that a failure (e.g. extension not installed on this
    # Postgres instance) does not abort the outer Alembic transaction.
    # On success the SAVEPOINT is released; on failure it is rolled back and we
    # continue — embedding column stays TEXT and cosine queries are no-ops.
    bind = op.get_bind()
    bind.execute(sa.text("SAVEPOINT before_vector_ext"))
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        bind.execute(sa.text("RELEASE SAVEPOINT before_vector_ext"))
    except Exception:
        bind.execute(sa.text("ROLLBACK TO SAVEPOINT before_vector_ext"))
        bind.execute(sa.text("RELEASE SAVEPOINT before_vector_ext"))

    # note_embeddings: stores per-note embedding vectors
    # Supports multiple models (different model_key / dim coexist in the same table)
    op.create_table(
        "note_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        # scope: "global" | "post"
        sa.Column("scope", sa.String(16), nullable=False),
        # note_id: JSONB id of the note (client-generated, may be non-UUID string)
        sa.Column("note_id", sa.Text, nullable=False),
        # post_id: only set for scope="post"
        sa.Column("post_id", sa.Text, nullable=True),
        # chunk_index: 0 for single-chunk notes, 1+ for long notes split into chunks
        sa.Column("chunk_index", sa.Integer, nullable=False, server_default="0"),
        # model_key: e.g. "local:multilingual-e5-small" or "openai:text-embedding-3-small"
        sa.Column("model_key", sa.Text, nullable=False),
        # dim: embedding dimensionality (redundant but useful for queries)
        sa.Column("dim", sa.Integer, nullable=False),
        # content_hash: sha256 of (title + body + model_key) for change detection
        sa.Column("content_hash", sa.Text, nullable=False),
        # embedding: stored as text[] representation; actual vector ops done via pgvector
        # We use TEXT to store as pgvector-encoded string for portability;
        # retrieval queries cast to vector on the fly.
        sa.Column("embedding", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "scope", "note_id", "chunk_index", "model_key",
                            name="uq_note_embeddings_note_chunk_model"),
    )
    op.create_index("ix_note_embeddings_lookup",
                    "note_embeddings", ["user_id", "scope", "model_key"])

    # embedding_jobs: durable async queue for indexing tasks
    op.create_table(
        "embedding_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        # op: "upsert" | "delete"
        sa.Column("op", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("note_id", sa.Text, nullable=False),
        sa.Column("post_id", sa.Text, nullable=True),
        # status: "pending" | "processing" | "done" | "failed"
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_embedding_jobs_pending",
                    "embedding_jobs", ["status", "enqueued_at"])


def downgrade() -> None:
    op.drop_table("embedding_jobs")
    op.drop_table("note_embeddings")
    # Do NOT drop the vector extension — other tables might use it.
