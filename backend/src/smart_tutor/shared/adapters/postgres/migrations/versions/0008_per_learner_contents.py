"""Per-learner contents (PRD v2.23 D18, §9.4; ADR 0011): contents keyed by (owner_id, sha256); uploads.document_id.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DUPLICATE_UPLOAD = "Duplicate uploads aren't supported yet"


def upgrade() -> None:
    op.add_column("contents", sa.Column("owner_id", sa.Text))
    # Duplicates failed until now, so each content has at most one owner's document.
    op.execute(
        "update contents c set owner_id = coalesce("
        "(select d.owner_id from documents d where d.content_id = c.content_id order by d.created_at limit 1),"
        " c.processed_by_user_id)"
    )
    op.alter_column("contents", "owner_id", nullable=False)
    op.drop_constraint("contents_sha256_key", "contents", type_="unique")
    op.create_unique_constraint("contents_owner_sha256", "contents", ["owner_id", "sha256"])
    op.drop_column("contents", "processed_by_user_id")
    # The document an upload ended in: its own, or the learner's existing one for a duplicate. No FK (delete).
    op.add_column("uploads", sa.Column("document_id", sa.Uuid(as_uuid=False)))
    op.execute(
        "update uploads u set document_id = d.document_id from documents d"
        " where d.upload_id = u.upload_id and d.content_id is not null"
    )
    # The interim duplicate failures have no file and can't be retried: remove them (the learner re-uploads).
    op.execute(
        sa.text(
            "delete from document_subjects where document_id in (select document_id from documents"
            " where content_id is null and failure_reason = :reason)"
        ).bindparams(reason=DUPLICATE_UPLOAD)
    )
    op.execute(
        sa.text("delete from documents where content_id is null and failure_reason = :reason").bindparams(
            reason=DUPLICATE_UPLOAD
        )
    )
    op.drop_constraint("documents_added_via", "documents", type_="check")
    op.create_check_constraint(
        "documents_added_via", "documents", "added_via in ('upload', 'share', 'public', 'import')"
    )


def downgrade() -> None:
    op.drop_constraint("documents_added_via", "documents", type_="check")
    op.create_check_constraint(
        "documents_added_via", "documents", "added_via in ('upload', 'dedupe', 'share', 'public', 'import')"
    )
    op.drop_column("uploads", "document_id")
    op.add_column("contents", sa.Column("processed_by_user_id", sa.Text))
    op.execute("update contents set processed_by_user_id = owner_id")
    op.drop_constraint("contents_owner_sha256", "contents", type_="unique")
    op.create_unique_constraint("contents_sha256_key", "contents", ["sha256"])  # fails if two learners share a file
    op.drop_column("contents", "owner_id")
