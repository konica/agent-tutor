"""Threads: one conversation, 1-3 subject ids, append-only (PRD §9.4).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "threads",
        sa.Column("thread_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("subject_ids", postgresql.ARRAY(sa.Uuid(as_uuid=False)), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_learner_message_at", sa.DateTime(timezone=True)),
        sa.Column("record_written_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("cardinality(subject_ids) between 1 and 3", name="threads_subject_count"),
        sa.CheckConstraint("status in ('active', 'archived')", name="threads_status"),
    )
    op.create_index("threads_user_created", "threads", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("threads_user_created", table_name="threads")
    op.drop_table("threads")
