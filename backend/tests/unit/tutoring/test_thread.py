from datetime import UTC, datetime

from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.tutoring.domain.thread import Thread, ThreadStatus


def test_a_new_thread_belongs_to_its_learner_and_records_the_first_question() -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    thread = Thread.start(ThreadId("t1"), UserId("ada"), now)
    assert thread.is_owned_by(UserId("ada")) and not thread.is_owned_by(UserId("bob"))
    assert thread.created_at == thread.last_learner_message_at == now
    assert thread.status is ThreadStatus.ACTIVE
