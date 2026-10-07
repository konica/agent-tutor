"""Subject name embeddings for suggestion ranking (PRD §9.4 `subjects.name_embedding`, §9.2 step 5).

The seeded "General" row gets its embedding from the worker at startup (no model calls in migrations).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024  # Nova multimodal embeddings, as chunks.embedding


def upgrade() -> None:
    op.add_column("subjects", sa.Column("name_embedding", Vector(EMBEDDING_DIM)))


def downgrade() -> None:
    op.drop_column("subjects", "name_embedding")
