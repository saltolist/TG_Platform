"""Store normalized keywords with phase 4 discovery nodes.

Revision ID: 021_discovery_keywords
Revises: 020_discovery_context
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "021_discovery_keywords"
down_revision: Union[str, None] = "020_discovery_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "note_embeddings",
        sa.Column(
            "keywords",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("note_embeddings", "keywords")
