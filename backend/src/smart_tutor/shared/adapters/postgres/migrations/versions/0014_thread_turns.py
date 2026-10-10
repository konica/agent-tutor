"""Thread turns: what a conversation's learner saw, for reopening it (PRD §9.4 Thread turn, US-13; ADR 0015).

Only turns whose answer ended with `done`. Citations are (n, document_id, chunk_id, page); titles resolve at read
time. No foreign key to documents, so turns outlive a deleted document. `user_id` is the thread's owner, for
owner-scoped reads.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thread_turns",
        sa.Column("turn_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("citations", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("decline_code", sa.Text),
        sa.Column("decline_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(decline_code IS NULL) = (decline_message IS NULL)", name="thread_turns_decline_pair"),
    )
    op.create_index("thread_turns_thread_idx", "thread_turns", ["thread_id", "turn_id"])


def downgrade() -> None:
    op.drop_table("thread_turns")
