from datetime import UTC, datetime

import pytest

from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.tutoring.domain.errors import ThreadSubjectsError
from smart_tutor.tutoring.domain.thread import Thread, ThreadStatus

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
A, B, C, D = (SubjectId(f"s{i}") for i in range(4))


def start(*subjects: SubjectId) -> Thread:
    return Thread.start(ThreadId("t1"), UserId("ada"), list(subjects), NOW)


def test_a_new_thread_is_active_owned_and_records_the_question_time() -> None:
    thread = start(A)
    assert thread.subject_ids == (A,)
    assert thread.status is ThreadStatus.ACTIVE
    assert thread.is_owned_by(UserId("ada")) and not thread.is_owned_by(UserId("bob"))
    assert thread.created_at == thread.last_learner_message_at == NOW


@pytest.mark.parametrize("subjects", [[], [A, B, C, D], [A, A]])
def test_a_thread_starts_with_one_to_three_distinct_subjects(subjects: list[SubjectId]) -> None:
    with pytest.raises(ThreadSubjectsError):
        start(*subjects)


def test_subjects_are_only_added_up_to_three() -> None:
    thread = start(A)
    assert thread.add_subject(B) is True
    assert thread.add_subject(B) is False  # already there: nothing changes
    assert thread.add_subject(C) is True
    with pytest.raises(ThreadSubjectsError):
        thread.add_subject(D)
    assert thread.subject_ids == (A, B, C)


def test_a_thread_has_no_way_to_remove_a_subject() -> None:
    assert not [name for name in dir(Thread) if "remove" in name or "discard" in name]


def test_a_pending_thread_has_no_subjects_until_bound() -> None:
    t = Thread.pending(ThreadId("t1"), UserId("ada"), "How do these methods handle long documents?", NOW)
    assert t.subject_ids == () and t.awaiting_subjects and t.title is not None and t.title.startswith("How do")
    assert t.last_learner_message_at == NOW


def test_start_keeps_the_title() -> None:
    t = Thread.start(ThreadId("t1"), UserId("ada"), [SubjectId("s1")], NOW, title="Q?")
    assert t.title == "Q?" and not t.awaiting_subjects
