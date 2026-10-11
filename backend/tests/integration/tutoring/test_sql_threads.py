"""SqlThreadRepository against the Compose Postgres (scratch database; see the plan's Global Constraints)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, inspect, select

from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import DocumentId, RunId, ThreadId, UserId
from smart_tutor.tutoring.adapters.sql_threads import SqlThreadRepository, thread_documents, thread_turns
from smart_tutor.tutoring.domain.thread import SearchScope, Thread, ThreadStatus
from smart_tutor.tutoring.domain.turn import Decline, Rating, Turn, TurnCitation

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


def test_set_title_stores_the_title(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC), title="What is attention?")
    repo.add(thread)

    repo.set_title(thread.thread_id, "Attention basics")

    stored = repo.get_owned(thread.thread_id, owner)
    assert stored is not None and stored.title == "Attention basics"


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


def test_keep_deleted_title_sets_the_title_on_the_owners_rows_only(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    now = datetime.now(UTC)
    ada, bob = UserId(f"ada-{uuid.uuid4()}"), UserId(f"bob-{uuid.uuid4()}")
    thread_a = Thread.start(ThreadId(str(uuid.uuid4())), ada, now)
    thread_b = Thread.start(ThreadId(str(uuid.uuid4())), bob, now)
    repo.add(thread_a)
    repo.add(thread_b)
    doc, other = DocumentId(str(uuid.uuid4())), DocumentId(str(uuid.uuid4()))
    repo.add_documents_used(thread_a.thread_id, [doc, other], now)
    repo.add_documents_used(thread_b.thread_id, [doc], now)

    repo.keep_deleted_title(ada, doc, "Chain-of-Thought Prompting")

    assert [(u.document_id, u.deleted_title) for u in repo.documents_used(thread_a.thread_id)] == [
        (doc, "Chain-of-Thought Prompting"),
        (other, None),
    ]
    assert [u.deleted_title for u in repo.documents_used(thread_b.thread_id)] == [None]


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


def test_a_row_inserted_as_before_0010_gets_the_column_defaults(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    thread = Thread.start(ThreadId(str(uuid.uuid4())), UserId("learner-a"), datetime(2026, 10, 9, tzinfo=UTC))
    repo.add(thread)
    doc = DocumentId(str(uuid.uuid4()))
    used_at = datetime(2026, 10, 9, 9, tzinfo=UTC)

    # An old API pod during a rolling deploy inserts without added_by and added_at.
    with engine.begin() as conn:
        conn.execute(
            thread_documents.insert().values(thread_id=thread.thread_id, document_id=doc, first_used_at=used_at)
        )

    rows = repo.documents_used(ThreadId(thread.thread_id))
    assert [(r.document_id, r.added_by, r.first_used_at) for r in rows] == [(doc, "answer", used_at)]


def test_a_thread_keeps_its_search_scope(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC))
    repo.add(thread)
    stored = repo.get_owned(thread.thread_id, owner)
    assert stored is not None and stored.search_scope is SearchScope.LIBRARY

    repo.set_search_scope(thread.thread_id, SearchScope.LISTED)

    stored = repo.get_owned(thread.thread_id, owner)
    assert stored is not None and stored.search_scope is SearchScope.LISTED


def test_turns_round_trip_oldest_first_for_the_owner_only(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC), title="Q1")
    repo.add(thread)
    doc = DocumentId(str(uuid.uuid4()))  # no row in documents: turns don't reference it
    t0 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    first = Turn(
        thread.thread_id,
        owner,
        "Q1",
        "A [1].",
        (TurnCitation(1, doc, "c1", 3), TurnCitation(2, doc, "c2", None)),
        None,
        t0,
    )
    second = Turn(thread.thread_id, owner, "Q2", "", (), Decline("limited", "These documents don't cover this."), t0)

    repo.add_turn(first, [doc])
    repo.add_turn(second, [])

    assert repo.turns(thread.thread_id, owner) == [first, second]
    assert repo.turns(thread.thread_id, UserId("bob")) == []
    assert [row.document_id for row in repo.documents_used(thread.thread_id)] == [doc]


def test_a_turn_row_holds_no_title_or_text_beyond_what_the_learner_saw(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC))
    repo.add(thread)
    doc = DocumentId(str(uuid.uuid4()))
    turn = Turn(thread.thread_id, owner, "Q", "A [1].", (TurnCitation(1, doc, "c1", 3),), None, datetime.now(UTC))
    repo.add_turn(turn, [doc])

    columns = {c["name"] for c in inspect(engine).get_columns("thread_turns")}
    assert columns == {
        "turn_id",
        "thread_id",
        "user_id",
        "question",
        "answer",
        "citations",
        "decline_code",
        "decline_message",
        "created_at",
        "run_id",
        "rating",
    }
    with engine.connect() as conn:
        [citations] = conn.execute(
            select(thread_turns.c.citations).where(thread_turns.c.thread_id == thread.thread_id)
        ).scalars()
    assert citations == [{"n": 1, "document_id": doc, "chunk_id": "c1", "page": 3}]


def test_a_turn_keeps_its_run_id_and_one_without_reads_none(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC))
    repo.add(thread)
    now = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
    run = RunId(str(uuid.uuid4()))
    with_run = Turn(thread.thread_id, owner, "Q1", "A.", (), None, now, run_id=run)
    without = Turn(thread.thread_id, owner, "Q2", "A.", (), None, now)

    repo.add_turn(with_run, [])
    repo.add_turn(without, [])

    assert [t.run_id for t in repo.turns(thread.thread_id, owner)] == [run, None]


def test_a_turns_rating_is_set_and_replaced_for_its_owner_only(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC))
    repo.add(thread)
    run = RunId(str(uuid.uuid4()))
    repo.add_turn(Turn(thread.thread_id, owner, "Q", "A.", (), None, datetime.now(UTC), run_id=run), [])

    assert repo.turns(thread.thread_id, owner)[0].rating is None
    assert repo.set_rating(thread.thread_id, owner, run, Rating.UP) is True
    assert repo.turns(thread.thread_id, owner)[0].rating is Rating.UP
    assert repo.set_rating(thread.thread_id, owner, run, Rating.DOWN) is True
    assert repo.turns(thread.thread_id, owner)[0].rating is Rating.DOWN

    assert repo.set_rating(thread.thread_id, UserId("bob"), run, Rating.UP) is False
    assert repo.turns(thread.thread_id, owner)[0].rating is Rating.DOWN
    assert repo.set_rating(thread.thread_id, owner, RunId(str(uuid.uuid4())), Rating.UP) is False


def test_list_owned_is_the_owners_threads_newest_activity_first(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner, other = UserId(f"ada-{uuid.uuid4()}"), UserId(f"bob-{uuid.uuid4()}")
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    older = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0, title="Older")
    newer = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(hours=1), title="Newer")
    archived = Thread(ThreadId(str(uuid.uuid4())), owner, t0, status=ThreadStatus.ARCHIVED)
    theirs = Thread.start(ThreadId(str(uuid.uuid4())), other, t0 + timedelta(hours=2))
    for t in (older, newer, archived, theirs):
        repo.add(t)

    assert [t.thread_id for t in repo.list_owned(owner, ThreadStatus.ACTIVE)] == [newer.thread_id, older.thread_id]

    repo.set_last_learner_message_at(older.thread_id, t0 + timedelta(hours=3))
    listed = repo.list_owned(owner, ThreadStatus.ACTIVE)
    assert [t.thread_id for t in listed] == [older.thread_id, newer.thread_id]
    assert listed[0].last_learner_message_at == t0 + timedelta(hours=3)
    assert [t.thread_id for t in repo.list_owned(owner, ThreadStatus.ARCHIVED)] == [archived.thread_id]


def test_a_thread_with_no_learner_message_sorts_by_its_start(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    quiet = Thread(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(hours=2))  # last_learner_message_at None
    asked = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(hours=1))
    repo.add(quiet)
    repo.add(asked)
    assert [t.thread_id for t in repo.list_owned(owner, ThreadStatus.ACTIVE)] == [quiet.thread_id, asked.thread_id]


def test_documents_used_by_thread_groups_each_threads_list_in_order(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    now = datetime.now(UTC)
    a = Thread.start(ThreadId(str(uuid.uuid4())), owner, now)
    b = Thread.start(ThreadId(str(uuid.uuid4())), owner, now)
    empty = Thread.start(ThreadId(str(uuid.uuid4())), owner, now)
    for t in (a, b, empty):
        repo.add(t)
    d1, d2, d3 = (DocumentId(str(uuid.uuid4())) for _ in range(3))
    repo.add_documents_used(a.thread_id, [d2, d1], now)
    repo.add_documents(b.thread_id, [d3], now)

    grouped = repo.documents_used_by_thread([a.thread_id, b.thread_id, empty.thread_id])

    assert [r.document_id for r in grouped[a.thread_id]] == [d2, d1]
    assert [r.document_id for r in grouped[b.thread_id]] == [d3]
    assert grouped.get(empty.thread_id, []) == []
    assert repo.documents_used_by_thread([]) == {}


def test_last_turns_are_the_newest_n_oldest_first_for_the_owner_only(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC), title="Q1")
    repo.add(thread)
    at = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
    for i in range(1, 8):
        repo.add_turn(Turn(thread.thread_id, owner, f"Q{i}", f"A{i}", (), None, at), [])

    assert [t.question for t in repo.last_turns(thread.thread_id, owner, 5)] == ["Q3", "Q4", "Q5", "Q6", "Q7"]
    assert repo.last_turns(thread.thread_id, owner, 0) == []
    assert repo.last_turns(thread.thread_id, UserId("bob"), 5) == []
