from datetime import UTC, datetime, timedelta

import pytest

from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.domain.errors import InvalidTitleError, NoListedDocumentsError, ThreadArchivedError
from smart_tutor.tutoring.domain.thread import SearchScope, Thread, ThreadFilter, ThreadStatus

NOW = datetime(2026, 10, 9, tzinfo=UTC)


def new_thread() -> Thread:
    return Thread.start(ThreadId("t1"), UserId("ada"), NOW, title="What is attention?")


def test_a_new_thread_is_titled_with_its_first_question() -> None:
    assert new_thread().title == "What is attention?"


def test_rename_trims_the_title() -> None:
    thread = new_thread()
    assert thread.rename("  Attention basics\n") == "Attention basics"
    assert thread.title == "Attention basics"


def test_rename_accepts_one_to_120_characters() -> None:
    thread = new_thread()
    assert thread.rename("A") == "A"
    assert thread.rename("x" * 120) == "x" * 120


@pytest.mark.parametrize(("title", "message"), [("", "Enter a title"), ("  \t ", "Enter a title"), ("x" * 121, "120")])
def test_rename_refuses_an_empty_or_too_long_title(title: str, message: str) -> None:
    thread = new_thread()
    with pytest.raises(InvalidTitleError, match=message):
        thread.rename(title)
    assert thread.title == "What is attention?"


def test_an_archived_thread_cannot_be_renamed() -> None:
    thread = new_thread()
    thread.status = ThreadStatus.ARCHIVED
    with pytest.raises(ThreadArchivedError):
        thread.rename("New")
    assert thread.title == "What is attention?"


def test_a_new_thread_belongs_to_its_learner_and_records_the_first_question() -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    thread = Thread.start(ThreadId("t1"), UserId("ada"), now)
    assert thread.is_owned_by(UserId("ada")) and not thread.is_owned_by(UserId("bob"))
    assert thread.created_at == thread.last_learner_message_at == now
    assert thread.status is ThreadStatus.ACTIVE


def test_a_new_thread_searches_the_library() -> None:
    assert new_thread().search_scope is SearchScope.LIBRARY


def test_limiting_the_search_needs_a_listed_document() -> None:
    thread = new_thread()
    with pytest.raises(NoListedDocumentsError, match="Add documents"):
        thread.limit_search(SearchScope.LISTED, 0)
    assert thread.search_scope is SearchScope.LIBRARY
    thread.limit_search(SearchScope.LISTED, 2)
    assert thread.search_scope is SearchScope.LISTED
    thread.limit_search(SearchScope.LIBRARY, 0)
    assert thread.search_scope is SearchScope.LIBRARY


def test_an_archived_thread_cannot_change_its_search_scope() -> None:
    thread = new_thread()
    thread.status = ThreadStatus.ARCHIVED
    with pytest.raises(ThreadArchivedError, match="Restore it first"):
        thread.limit_search(SearchScope.LISTED, 1)


def test_last_activity_is_the_last_learner_message_or_the_start() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    assert Thread(ThreadId("t"), UserId("ada"), start).last_activity == start
    later = start + timedelta(hours=2)
    assert Thread(ThreadId("t"), UserId("ada"), start, last_learner_message_at=later).last_activity == later


def test_asking_moves_the_last_learner_message() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    thread = Thread.start(ThreadId("t"), UserId("ada"), start)
    thread.ask(start + timedelta(minutes=5))
    assert thread.last_learner_message_at == start + timedelta(minutes=5)


def test_an_archived_thread_takes_no_question() -> None:
    thread = Thread(ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC), status=ThreadStatus.ARCHIVED)
    with pytest.raises(ThreadArchivedError):
        thread.ask(datetime(2026, 10, 2, tzinfo=UTC))


def test_no_filter_matches_every_thread() -> None:
    thread = Thread.start(ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC), title="Q?")
    assert thread.matches(ThreadFilter(), [])


def test_matches_by_last_activity_from_inclusive_and_before_exclusive() -> None:
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    thread = Thread.start(ThreadId("t"), UserId("ada"), at)
    assert thread.matches(ThreadFilter(active_from=at, active_before=at + timedelta(seconds=1)), [])
    assert not thread.matches(ThreadFilter(active_from=at + timedelta(seconds=1)), [])
    assert not thread.matches(ThreadFilter(active_before=at), [])


def test_matches_when_any_listed_document_is_one_of_the_filters() -> None:
    thread = Thread.start(ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC))
    d1, d2 = DocumentId("d1"), DocumentId("d2")
    assert thread.matches(ThreadFilter(document_ids=frozenset({d2})), [d1, d2])
    assert not thread.matches(ThreadFilter(document_ids=frozenset({d2})), [d1])
    assert not thread.matches(ThreadFilter(document_ids=frozenset()), [d1])


def test_title_matches_case_insensitively_and_literally() -> None:
    thread = Thread.start(
        ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC), title="Is RAG 100% grounded?"
    )
    assert thread.matches(ThreadFilter(title="rag"), [])
    assert thread.matches(ThreadFilter(title="100%"), [])
    assert not thread.matches(ThreadFilter(title="1_0"), [])
    untitled = Thread.start(ThreadId("u"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC))
    assert not untitled.matches(ThreadFilter(title="rag"), [])
