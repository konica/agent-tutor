"""Library: contents, uploads, documents, subjects, document_subjects; seed the subject "General" (PRD §9.4).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENERAL_SUBJECT_ID = "00000000-0000-4000-8000-000000000001"


def _created_at() -> sa.Column[Any]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    subjects = op.create_table(
        "subjects",
        sa.Column("subject_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("canonical_name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False, unique=True),
        _created_at(),
    )
    op.bulk_insert(
        subjects, [{"subject_id": GENERAL_SUBJECT_ID, "canonical_name": "General", "normalized_name": "general"}]
    )
    op.create_table(
        "contents",
        sa.Column("content_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("pages", sa.Integer),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("failure_reason", sa.Text),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_by_user_id", sa.Text),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        _created_at(),
        sa.CheckConstraint("state in ('processing', 'ready', 'failed')", name="contents_state"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="contents_sha256_hex"),
    )
    op.create_table(
        "uploads",
        sa.Column("upload_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("bytes", sa.BigInteger),
        _created_at(),
        sa.Column("outcome", sa.Text),
        sa.CheckConstraint("outcome in ('stored', 'duplicate')", name="uploads_outcome"),
    )
    op.create_index("uploads_user_created", "uploads", ["user_id", "created_at"])
    op.create_table(
        "documents",
        sa.Column("document_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("content_id", sa.Uuid(as_uuid=False), sa.ForeignKey("contents.content_id")),
        sa.Column("upload_id", sa.Uuid(as_uuid=False), sa.ForeignKey("uploads.upload_id"), nullable=False, unique=True),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("failure_reason", sa.Text),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("visibility", sa.Text, nullable=False, server_default="private"),
        sa.Column("title_override", sa.Text),
        sa.Column("added_via", sa.Text, nullable=False, server_default="upload"),
        _created_at(),
        # NULL content_ids are distinct in Postgres, so many unhashed documents per learner are fine.
        sa.UniqueConstraint("owner_id", "content_id", name="documents_owner_content"),
        sa.CheckConstraint("state in ('processing', 'awaiting_subjects', 'ready', 'failed')", name="documents_state"),
        sa.CheckConstraint("visibility in ('private', 'shared', 'public')", name="documents_visibility"),
        sa.CheckConstraint(
            "added_via in ('upload', 'dedupe', 'share', 'public', 'import')", name="documents_added_via"
        ),
    )
    op.create_index("documents_owner_created", "documents", ["owner_id", "created_at"])
    op.create_table(
        "document_subjects",
        sa.Column("document_id", sa.Uuid(as_uuid=False), sa.ForeignKey("documents.document_id"), primary_key=True),
        sa.Column("subject_id", sa.Uuid(as_uuid=False), sa.ForeignKey("subjects.subject_id"), primary_key=True),
    )


def downgrade() -> None:
    for table in ("document_subjects", "documents", "uploads", "contents", "subjects"):
        op.drop_table(table)
