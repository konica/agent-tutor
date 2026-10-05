"""Chunks with pgvector embeddings; how a content was processed (PRD §9.4).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024  # Nova multimodal embeddings


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for column in ("text_key", "chunker", "embedding_model"):
        op.add_column("contents", sa.Column(column, sa.Text))
    op.add_column("contents", sa.Column("embedding_dim", sa.Integer))
    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("content_id", sa.Uuid(as_uuid=False), sa.ForeignKey("contents.content_id"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("page", sa.Integer),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.UniqueConstraint("content_id", "seq", name="chunks_content_seq"),
        sa.CheckConstraint("page is null or page >= 1", name="chunks_page_positive"),
    )
    op.create_index(
        "chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("chunks_embedding_hnsw", table_name="chunks")
    op.drop_table("chunks")
    for column in ("embedding_dim", "embedding_model", "chunker", "text_key"):
        op.drop_column("contents", column)
