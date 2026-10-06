"""Content description from the first-pages step and the work key (PRD §9.4).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024  # Nova multimodal embeddings, as chunks.embedding


def upgrade() -> None:
    op.add_column("contents", sa.Column("title", sa.Text))
    op.add_column("contents", sa.Column("authors", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"))
    op.add_column("contents", sa.Column("year", sa.Integer))
    op.add_column("contents", sa.Column("doi", sa.Text))
    op.add_column("contents", sa.Column("summary", sa.Text))
    op.add_column("contents", sa.Column("summary_embedding", Vector(EMBEDDING_DIM)))
    op.add_column(
        "contents",
        sa.Column("proposed_subject_names", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
    )
    op.add_column("contents", sa.Column("work_key", sa.Text))
    op.create_index("contents_work_key", "contents", ["work_key"])  # the research map groups contents by work


def downgrade() -> None:
    op.drop_index("contents_work_key", table_name="contents")
    for column in (
        "work_key",
        "proposed_subject_names",
        "summary_embedding",
        "summary",
        "doi",
        "year",
        "authors",
        "title",
    ):
        op.drop_column("contents", column)
