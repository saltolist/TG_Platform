"""add profiles.summary_catalog

Revision ID: 003_summary_catalog
Revises: 002_user_is_seed
Create Date: 2026-06-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_summary_catalog"
down_revision: Union[str, None] = "002_user_is_seed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("summary_catalog", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("profiles", "summary_catalog")
