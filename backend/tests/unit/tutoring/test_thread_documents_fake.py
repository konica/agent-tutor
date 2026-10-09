"""The in-memory threads keep documents used like the SQL repository does."""

import uuid
from datetime import UTC, datetime

from fakes.tutoring import InMemoryThreads
from smart_tutor.shared.domain.ids import DocumentId, ThreadId


def test_documents_used_keep_first_use_order_without_duplicates() -> None:
    repo = InMemoryThreads()
    thread_id = ThreadId(str(uuid.uuid4()))
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    t1 = datetime(2026, 10, 2, tzinfo=UTC)
    d1, d2, d3 = (DocumentId(str(uuid.uuid4())) for _ in range(3))
    repo.add_documents_used(thread_id, [d1, d2], t0)
    repo.add_documents_used(thread_id, [d2, d3, d1], t1)
    repo.add_documents_used(thread_id, [], t1)

    used = repo.documents_used(thread_id)

    assert [u.document_id for u in used] == [d1, d2, d3]
    assert [u.first_used_at for u in used] == [t0, t0, t1]
    assert all(u.deleted_title is None and u.thread_id == thread_id for u in used)


def test_a_thread_with_no_documents_used_lists_none() -> None:
    assert InMemoryThreads().documents_used(ThreadId(str(uuid.uuid4()))) == []


T0 = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 9, 9, 5, tzinfo=UTC)


def test_learner_added_documents_are_listed_unused_until_an_answer_uses_them() -> None:
    threads = InMemoryThreads()
    t, a, b = ThreadId("t"), DocumentId("a"), DocumentId("b")
    threads.add_documents_used(t, [a], T0)
    threads.add_documents(t, [b, a], T1)  # a is listed already

    threads.add_documents_used(t, [b], T1)

    rows = threads.documents_used(t)
    assert [(r.document_id, r.added_by, r.first_used_at) for r in rows] == [(a, "answer", T0), (b, "learner", T1)]


def test_a_removed_document_comes_back_when_added_again() -> None:
    threads = InMemoryThreads()
    t, a = ThreadId("t"), DocumentId("a")
    threads.add_documents_used(t, [a], T0)
    threads.remove_document(t, a)
    assert threads.documents_used(t) == []
    threads.add_documents(t, [a], T1)
    [row] = threads.documents_used(t)
    assert (row.added_by, row.added_at, row.first_used_at) == ("learner", T1, None)
