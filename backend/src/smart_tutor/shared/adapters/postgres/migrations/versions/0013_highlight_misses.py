"""A content-free count of citation highlights the viewer couldn't draw (PRD §9.4, §10.1): highlight_misses.

One row per UTC day. No user id, chunk, document, or text.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "highlight_misses",
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("misses", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("highlight_misses")
