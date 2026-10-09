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
