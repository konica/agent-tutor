"""SQLAlchemy Core views of the library tables (the schema itself lives in the Alembic migrations)."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table, Text, Uuid

metadata = MetaData()

contents = Table(
    "contents",
    metadata,
    Column("content_id", Uuid(as_uuid=False), primary_key=True),
    Column("sha256", String(64)),
    Column("s3_key", Text),
    Column("bytes", BigInteger),
    Column("state", Text),
    Column("attempts", Integer),
    Column("processed_by_user_id", Text),
    Column("processed_at", DateTime(timezone=True)),
)

uploads = Table(
    "uploads",
    metadata,
    Column("upload_id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Text),
    Column("bytes", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("outcome", Text),
)

documents = Table(
    "documents",
    metadata,
    Column("document_id", Uuid(as_uuid=False), primary_key=True),
    Column("owner_id", Text),
    Column("content_id", Uuid(as_uuid=False)),
    Column("upload_id", Uuid(as_uuid=False)),
    Column("file_name", Text),
    Column("state", Text),
    Column("failure_reason", Text),
    Column("archived", Boolean),
    Column("title_override", Text),
    Column("created_at", DateTime(timezone=True)),
)
