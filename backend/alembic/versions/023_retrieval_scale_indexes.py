"""Concurrent lexical and metadata retrieval indexes.

Revision ID: 023_retrieval_scale_indexes
Revises: 022_agent_batch_scale
"""

from typing import Sequence, Union

from alembic import op

revision: str = "023_retrieval_scale_indexes"
down_revision: Union[str, None] = "022_agent_batch_scale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A terminated concurrent build leaves an invalid index behind. Dropping
    # named phase-8 indexes first makes retrying a version-unstamped migration
    # deterministic without touching any pre-phase-8 index.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_note_embeddings_discovery_fts")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY ix_note_embeddings_discovery_fts
            ON note_embeddings USING gin (
              to_tsvector(
                'simple'::regconfig,
                COALESCE(object_title, '') || ' ' ||
                COALESCE(NULLIF(search_text, ''), chunk_text) || ' ' ||
                COALESCE(keywords::text, '')
              )
            )
            """
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_note_embeddings_retrieval_metadata")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY ix_note_embeddings_retrieval_metadata
            ON note_embeddings (
              user_id, tenant_key, model_key, scope, node_type,
              object_status, index_revision, note_id
            )
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_note_embeddings_retrieval_metadata")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_note_embeddings_discovery_fts")
