"""Thread documents the learner adds (PRD §9.4, US-4c): who added a row and when; first use may be pending.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every existing row came from an answer, added when first used.
    # The defaults stay: code from before 0010 (an old pod during a rolling deploy) inserts without these columns.
    op.add_column("thread_documents", sa.Column("added_by", sa.Text, nullable=False, server_default="answer"))
    op.add_column("thread_documents", sa.Column("added_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE thread_documents SET added_at = first_used_at")
    op.alter_column("thread_documents", "added_at", nullable=False, server_default=sa.func.now())
    op.create_check_constraint("thread_documents_added_by", "thread_documents", "added_by IN ('answer', 'learner')")
    op.alter_column("thread_documents", "first_used_at", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM thread_documents WHERE first_used_at IS NULL")
    op.alter_column("thread_documents", "first_used_at", nullable=False)
    op.drop_constraint("thread_documents_added_by", "thread_documents")
    op.drop_column("thread_documents", "added_at")
    op.drop_column("thread_documents", "added_by")
