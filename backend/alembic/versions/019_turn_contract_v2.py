"""Persist versioned phase-2 turn contracts.

Revision ID: 019_turn_contract_v2
Revises: 018_normalize_post_uuid_ids
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "019_turn_contract_v2"
down_revision: Union[str, None] = "018_normalize_post_uuid_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialog_evidence_turns",
        sa.Column("turn_contract", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dialog_evidence_turns", "turn_contract")
