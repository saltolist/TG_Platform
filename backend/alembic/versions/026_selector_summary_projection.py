"""Add the compact selector summary projection.

Revision ID: 026_selector_summary_projection
Revises: 025_dialog_message_context
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026_selector_summary_projection"
down_revision: Union[str, None] = "025_dialog_message_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("note_embeddings", sa.Column("selector_summary", sa.Text(), nullable=True))
    op.add_column(
        "note_embeddings",
        sa.Column("selector_summary_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("note_embeddings", "selector_summary_version")
    op.drop_column("note_embeddings", "selector_summary")
