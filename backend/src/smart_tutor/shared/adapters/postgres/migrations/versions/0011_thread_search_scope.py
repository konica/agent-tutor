"""A thread can limit its search to the documents it lists (PRD §9.4, US-4c): threads.search_scope.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The default stays: code from before 0011 (an old pod during a rolling deploy) inserts threads without it.
    op.add_column("threads", sa.Column("search_scope", sa.Text, nullable=False, server_default="library"))
    op.create_check_constraint("threads_search_scope", "threads", "search_scope IN ('library', 'listed')")


def downgrade() -> None:
    op.drop_constraint("threads_search_scope", "threads")
    op.drop_column("threads", "search_scope")
