"""InMemoryThreads keeps turns per owner, oldest first, with the documents of each turn."""

from datetime import UTC, datetime

from fakes import InMemoryThreads
from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.application import Decline, Thread, Turn, TurnCitation

T0 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
ADA, BOB = UserId("ada"), UserId("bob")
D1 = DocumentId("00000000-0000-4000-8000-000000000001")


def started() -> tuple[InMemoryThreads, ThreadId]:
    threads = InMemoryThreads()
    thread = Thread.start(ThreadId("00000000-0000-4000-8000-0000000000a1"), ADA, T0, title="Q1")
    threads.add(thread)
    return threads, ThreadId(thread.thread_id)


def test_turns_are_kept_oldest_first_for_the_owner_only() -> None:
    threads, t = started()
    first = Turn(t, ADA, "Q1", "A1 [1].", (TurnCitation(1, D1, "c1", 3),), None, T0)
    second = Turn(t, ADA, "Q2", "", (), Decline("limited", "These documents don't cover this."), T0)
    threads.add_turn(first, [D1])
    threads.add_turn(second, [])

    assert threads.turns(t, ADA) == [first, second]
    assert threads.turns(t, BOB) == []
    assert [row.document_id for row in threads.documents_used(t)] == [D1]


def test_last_turns_are_the_newest_n_oldest_first_for_the_owner_only() -> None:
    threads, t = started()
    for i in range(1, 5):
        threads.add_turn(Turn(t, ADA, f"Q{i}", f"A{i}", (), None, T0), [])

    assert [x.question for x in threads.last_turns(t, ADA, 2)] == ["Q3", "Q4"]
    assert threads.last_turns(t, ADA, 0) == []
    assert threads.last_turns(t, BOB, 5) == []
