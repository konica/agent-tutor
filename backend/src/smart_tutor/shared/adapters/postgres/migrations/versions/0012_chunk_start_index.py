"""Each chunk's offset in its page's cleaned text, for the viewer's highlight (PRD §9.4, US-4b): chunks.start_index.

Nullable: existing chunks get it from the worker's backfill, and one whose text can't be located stays null.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("start_index", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "start_index")
