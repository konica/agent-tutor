"""Pending threads: a thread may have no subjects until the learner picks them (PRD US-3, detection unsure).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("threads_subject_count", "threads", type_="check")
    op.create_check_constraint("threads_subject_count", "threads", "cardinality(subject_ids) between 0 and 3")


def downgrade() -> None:
    op.drop_constraint("threads_subject_count", "threads", type_="check")
    op.create_check_constraint("threads_subject_count", "threads", "cardinality(subject_ids) between 1 and 3")
