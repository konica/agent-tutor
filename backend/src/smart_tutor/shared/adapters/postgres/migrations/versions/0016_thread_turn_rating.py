"""The learner's rating of a kept turn (PRD §10.2, #227): "up" or "down", null until rated.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("thread_turns", sa.Column("rating", sa.Text()))
    op.create_check_constraint("thread_turns_rating", "thread_turns", "rating IN ('up', 'down')")


def downgrade() -> None:
    op.drop_constraint("thread_turns_rating", "thread_turns", type_="check")
    op.drop_column("thread_turns", "rating")
