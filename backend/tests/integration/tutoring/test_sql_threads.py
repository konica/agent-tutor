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


def test_learner_added_documents_keep_their_place_and_are_marked_used(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    thread = Thread.start(ThreadId(str(uuid.uuid4())), UserId("learner-a"), datetime(2026, 10, 9, tzinfo=UTC))
    repo.add(thread)
    t = ThreadId(thread.thread_id)
    a, b, c = (DocumentId(str(uuid.uuid4())) for _ in range(3))
    t0, t1, t2 = (datetime(2026, 10, 9, 9, m, tzinfo=UTC) for m in (0, 5, 10))

    repo.add_documents_used(t, [a], t0)
    repo.add_documents(t, [c, b, a], t1)  # a is listed already
    repo.add_documents_used(t, [b], t2)

    rows = repo.documents_used(t)
    assert [(r.document_id, r.added_by, r.first_used_at) for r in rows] == [
        (a, "answer", t0),
        (c, "learner", None),
        (b, "learner", t2),
    ]

    repo.remove_document(t, c)
    repo.remove_document(t, c)  # not listed: nothing happens
    assert [r.document_id for r in repo.documents_used(t)] == [a, b]
