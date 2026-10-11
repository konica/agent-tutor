"""The ask's LangSmith run id with its turn (PRD §10.4, #221), so a rating can attach to its trace (#227).

Nullable: turns kept before it have none.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("thread_turns", sa.Column("run_id", sa.Uuid(as_uuid=False)))


def downgrade() -> None:
    op.drop_column("thread_turns", "run_id")
