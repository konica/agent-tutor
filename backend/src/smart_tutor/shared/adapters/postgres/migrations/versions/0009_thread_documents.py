"""Thread documents: the documents a thread drew on (PRD §9.4, US-4b).

No foreign key to documents, so rows outlive a deleted document.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thread_documents",
        sa.Column(
            "thread_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("first_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_title", sa.Text),
        # Documents of one turn share first_used_at; seq keeps their order.
        sa.Column("seq", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "document_id"),
    )


def downgrade() -> None:
    op.drop_table("thread_documents")
