"""tenant overlay notes + tenant_key on RAG tables

Revision ID: 008_tenant_overlay_rag
Revises: 007_encrypt_profile_secrets
Create Date: 2026-06-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008_tenant_overlay_rag"
down_revision: Union[str, None] = "007_encrypt_profile_secrets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "note_embeddings",
        sa.Column("tenant_key", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "embedding_jobs",
        sa.Column("tenant_key", sa.Text(), nullable=False, server_default=""),
    )

    op.drop_constraint("uq_note_embeddings_note_chunk_model", "note_embeddings", type_="unique")
    op.create_unique_constraint(
        "uq_note_embeddings_note_chunk_model",
        "note_embeddings",
        ["user_id", "tenant_key", "scope", "note_id", "chunk_index", "model_key"],
    )

    op.create_table(
        "tenant_overlay_notes",
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
        sa.Column("tenant_key", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("note_id", sa.Text(), nullable=False),
        sa.Column("post_id", sa.Text(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "tenant_key",
            "scope",
            "note_id",
            name="uq_tenant_overlay_notes",
        ),
    )
    op.create_index(
        "ix_tenant_overlay_notes_lookup",
        "tenant_overlay_notes",
        ["user_id", "tenant_key", "scope"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_overlay_notes_lookup", table_name="tenant_overlay_notes")
    op.drop_table("tenant_overlay_notes")

    op.drop_constraint("uq_note_embeddings_note_chunk_model", "note_embeddings", type_="unique")
    op.create_unique_constraint(
        "uq_note_embeddings_note_chunk_model",
        "note_embeddings",
        ["user_id", "scope", "note_id", "chunk_index", "model_key"],
    )

    op.drop_column("embedding_jobs", "tenant_key")
    op.drop_column("note_embeddings", "tenant_key")
