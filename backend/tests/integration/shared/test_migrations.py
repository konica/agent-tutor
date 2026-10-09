"""Against the Compose Postgres (`make up`)."""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine, make_url, text

from smart_tutor.shared.adapters.postgres.migrate import MIGRATIONS, escape_percent, upgrade_to_head
from smart_tutor.shared.config import Settings

pytestmark = pytest.mark.integration


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", escape_percent(url))
    return config


def test_upgrade_to_head_reaches_head_and_is_repeatable() -> None:
    url = Settings().database_url
    upgrade_to_head(url)
    upgrade_to_head(url)  # running twice is a no-op
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    with create_engine(url).connect() as conn:
        assert conn.execute(text("select version_num from alembic_version")).scalar_one() == head


def test_general_subject_is_seeded() -> None:
    url = Settings().database_url
    upgrade_to_head(url)
    with create_engine(url).connect() as conn:
        name = conn.execute(text("select canonical_name from subjects where normalized_name = 'general'"))
        assert name.scalar_one() == "General"


@pytest.fixture
def empty_database() -> Iterator[str]:
    """A throwaway database next to the configured one, so a test can migrate from an older revision."""
    base = make_url(Settings().database_url)
    name = f"smart_tutor_migration_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'create database "{name}"'))
    url = base.set(database=name)
    with create_engine(url, isolation_level="AUTOCOMMIT").connect() as conn:
        conn.execute(text("create extension if not exists vector"))  # local/postgres/init does this for the app DB
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'drop database if exists "{name}" with (force)'))
        admin.dispose()


GENERAL = "00000000-0000-4000-8000-000000000001"
DUPLICATE_UPLOAD = "Duplicate uploads aren't supported yet"


def ids(*names: str) -> dict[str, str]:
    return {n: str(uuid.uuid4()) for n in names}


def seed_0007(conn: Connection, i: dict[str, str], sha1: str, sha2: str) -> None:
    """Rows as Release 1 wrote them before per-learner contents."""
    conn.execute(
        text(
            "insert into uploads (upload_id, user_id, bytes, outcome) values"
            " (:u1, 'ada', 10, 'stored'), (:u2, 'ada', 10, 'duplicate'), (:u3, 'bob', null, null)"
        ),
        i,
    )
    conn.execute(
        text(
            "insert into contents (content_id, sha256, s3_key, bytes, state, processed_by_user_id) values"
            " (:c1, :sha1, 'contents/c1.pdf', 10, 'ready', 'someone-else'),"
            " (:c2, :sha2, 'contents/c2.pdf', 10, 'failed', 'bob')"
        ),
        {**i, "sha1": sha1, "sha2": sha2},
    )
    conn.execute(
        text(
            "insert into documents (document_id, owner_id, content_id, upload_id, file_name, state, failure_reason)"
            " values (:d1, 'ada', :c1, :u1, 'a.pdf', 'ready', null),"
            " (:d2, 'ada', null, :u2, 'a-again.pdf', 'failed', :dup),"
            " (:d3, 'bob', null, :u3, 'b.pdf', 'failed', 'This file isn''t a readable PDF')"
        ),
        {**i, "dup": DUPLICATE_UPLOAD},
    )
    conn.execute(
        text("insert into document_subjects (document_id, subject_id) values (:d1, :g), (:d2, :g)"),
        {**i, "g": GENERAL},
    )


def test_0008_keys_contents_by_owner_and_keeps_existing_data(empty_database: str) -> None:
    config = alembic_config(empty_database)
    command.upgrade(config, "0007")
    engine = create_engine(empty_database)
    i = ids("u1", "u2", "u3", "c1", "c2", "d1", "d2", "d3")
    sha1, sha2 = "1" * 64, "2" * 64
    with engine.begin() as conn:
        seed_0007(conn, i, sha1, sha2)

    command.upgrade(config, "head")

    with engine.connect() as conn:
        owners = dict(conn.execute(text("select content_id::text, owner_id from contents")).all())
        documents = {r[0] for r in conn.execute(text("select document_id::text from documents"))}
        subjects = {r[0] for r in conn.execute(text("select document_id::text from document_subjects"))}
        uploads = dict(conn.execute(text("select upload_id::text, document_id::text from uploads")).all())
        columns = conn.execute(text("select column_name from information_schema.columns where table_name = 'contents'"))
        column_names = {r[0] for r in columns}
        added_via = conn.execute(
            text("select pg_get_constraintdef(oid) from pg_constraint where conname = 'documents_added_via'")
        ).scalar_one()
    assert owners == {i["c1"]: "ada", i["c2"]: "bob"}  # the document's owner wins; else who processed it
    assert "processed_by_user_id" not in column_names
    assert documents == {i["d1"], i["d3"]}  # the interim duplicate failure is gone
    assert subjects == {i["d1"]}
    assert uploads == {i["u1"]: i["d1"], i["u2"]: None, i["u3"]: None}
    assert "dedupe" not in added_via

    # Round trip: down to 0007 and back up keeps the owners.
    command.downgrade(config, "0007")
    with engine.connect() as conn:
        processed_by = dict(conn.execute(text("select content_id::text, processed_by_user_id from contents")).all())
    assert processed_by == {i["c1"]: "ada", i["c2"]: "bob"}
    command.upgrade(config, "head")

    # Now another learner may hold the same bytes; one learner still may not hold them twice.
    insert = text(
        "insert into contents (content_id, sha256, s3_key, bytes, state, owner_id)"
        " values (:c, :s, 'k', 10, 'processing', :o)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"c": str(uuid.uuid4()), "s": sha1, "o": "bob"})
    with pytest.raises(Exception, match="contents_owner_sha256"), engine.begin() as conn:
        conn.execute(insert, {"c": str(uuid.uuid4()), "s": sha1, "o": "ada"})
    engine.dispose()
