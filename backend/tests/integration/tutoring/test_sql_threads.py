"""SqlThreadRepository against the Compose Postgres (scratch database; see the plan's Global Constraints)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, inspect

from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.adapters.sql_threads import SqlThreadRepository
from smart_tutor.tutoring.domain.thread import Thread

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = Settings().database_url
    upgrade_to_head(url)
    return create_db_engine(url)


def test_a_thread_round_trips_for_its_owner_only(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC))
    repo.add(thread)
    assert repo.get_owned(thread.thread_id, owner) == thread
    assert repo.get_owned(thread.thread_id, UserId("bob")) is None


def test_the_table_has_no_subject_column(engine: Engine) -> None:
    assert "subject_ids" not in {column["name"] for column in inspect(engine).get_columns("threads")}


def test_documents_used_keep_first_use_order_without_duplicates(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    t1 = datetime(2026, 10, 2, tzinfo=UTC)
    thread = Thread.start(ThreadId(str(uuid.uuid4())), UserId(f"ada-{uuid.uuid4()}"), t0)
    repo.add(thread)
    d1, d2, d3 = (DocumentId(str(uuid.uuid4())) for _ in range(3))
    repo.add_documents_used(thread.thread_id, [d1, d2], t0)
    repo.add_documents_used(thread.thread_id, [d2, d3, d1], t1)
    repo.add_documents_used(thread.thread_id, [], t1)

    used = repo.documents_used(thread.thread_id)

    assert [u.document_id for u in used] == [d1, d2, d3]
    assert [u.first_used_at for u in used] == [t0, t0, t1]
    assert all(u.deleted_title is None and u.thread_id == thread.thread_id for u in used)
