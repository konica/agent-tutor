"""Threads have no subjects (PRD v2.23 §9.4, Q55): drop threads.subject_ids.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("threads_subject_count", "threads", type_="check")
    op.drop_column("threads", "subject_ids")


def downgrade() -> None:
    # Old rows can't regain their subjects; they come back empty, so the 1-3 check isn't restored.
    op.add_column(
        "threads",
        sa.Column("subject_ids", postgresql.ARRAY(sa.Uuid(as_uuid=False)), nullable=False, server_default="{}"),
    )
