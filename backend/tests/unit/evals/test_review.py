"""The human review gate (PRD §10.3 item 6): candidates go to a Langfuse annotation queue as traces, and only the
ones a reviewer accepted come back as examples."""

from dataclasses import replace
from datetime import UTC, datetime

from evals.dataset import Dataset, Example
from evals.review import (
    ACCEPTED,
    ENVIRONMENT,
    RUBRIC,
    Candidate,
    Reviewed,
    candidates_name,
    ensure_queue,
    reviewed,
    submit,
)
from fakes.langfuse import FakeLangfuse

ASK = Dataset("ask", "smart-tutor-ask", "", (Example({"question": "hand"}, {"covered": True}),))
INJECTION = Dataset("injection", "smart-tutor-injection", "", (Example({"question": "seed"}, {}),))


def candidate(question: str, kind: str = "factual", covered: bool = True) -> Candidate:
    return Candidate(
        inputs={"question": question, "learner": "learner@example.com", "documents": None},
        expected={"covered": covered, "sources": ["react-2022"] if covered else [], "chunks": ["react-2022:4"]},
        type=kind,
        evidence=({"chunk": "react-2022:4", "text": "ReAct interleaves reasoning and acting."},),
    )


def test_the_queue_is_created_once_with_the_rubric_and_a_boolean_accepted_score() -> None:
    client = FakeLangfuse()
    first, again = ensure_queue(client, ASK), ensure_queue(client, ASK)
    assert first == again and len(client.queues) == 1
    queue = client.queues[first]
    assert queue.name == candidates_name(ASK) == "smart-tutor-ask-candidates"
    assert queue.description.endswith(RUBRIC) and "smart-tutor-ask" in queue.description
    [config_id] = queue.score_config_ids
    assert client.score_configs[config_id][0] == ACCEPTED


def test_every_dataset_queue_shares_the_one_accepted_score_config() -> None:
    client = FakeLangfuse()
    ask, injection = ensure_queue(client, ASK), ensure_queue(client, INJECTION, "Accept realistic attacks.")
    assert len(client.score_configs) == 1
    assert client.queues[ask].score_config_ids == client.queues[injection].score_config_ids
    assert client.queues[injection].description.endswith("Accept realistic attacks.")


def test_submitted_candidates_are_traces_in_the_queue_with_their_evidence() -> None:
    client = FakeLangfuse()
    ids = submit(client, ASK, [candidate("What is ReAct?"), candidate("Is X?", "unanswerable", False)], {"batch": "b1"})
    [queue] = client.queues.values()
    assert queue.trace_ids == ids
    trace = client.traces_by_id[ids[1]]
    assert trace.name == "smart-tutor-ask-candidates" and trace.environment == ENVIRONMENT == "local"
    assert len(trace.id) == 32 and int(trace.id, 16) >= 0  # Langfuse trace ids are 32 lowercase hex characters
    assert trace.input["question"] == "Is X?"
    assert trace.output == {
        "expected": {"covered": False, "sources": [], "chunks": ["react-2022:4"]},
        "type": "unanswerable",
        "evidence": [{"chunk": "react-2022:4", "text": "ReAct interleaves reasoning and acting."}],
    }
    assert trace.metadata == {
        "dataset": "smart-tutor-ask",
        "type": "unanswerable",
        "generated_at": trace.timestamp.isoformat(timespec="microseconds"),
        "batch": "b1",
    }


def test_candidates_of_one_batch_are_generated_in_order_a_millisecond_apart() -> None:
    client = FakeLangfuse()
    ids = submit(client, ASK, [candidate("a"), candidate("b"), candidate("c")], {})
    times = [client.traces_by_id[i].timestamp for i in ids]
    assert all((later - earlier).total_seconds() == 0.001 for earlier, later in zip(times, times[1:], strict=False))


def test_an_existing_queue_is_reused() -> None:
    client = FakeLangfuse()
    first = submit(client, ASK, [candidate("a")], {})
    second = submit(client, ASK, [candidate("b")], {})
    [queue] = client.queues.values()
    assert queue.trace_ids == [*first, *second]


def test_only_items_whose_latest_score_accepts_them_are_accepted() -> None:
    client = FakeLangfuse()
    kept, rejected, unscored, changed = submit(
        client, ASK, [candidate("kept"), candidate("rejected"), candidate("unscored"), candidate("changed")], {}
    )
    client.score(kept, ACCEPTED, 1)
    client.score(rejected, ACCEPTED, 0)
    client.score(changed, ACCEPTED, 1)
    client.score(changed, ACCEPTED, 0)  # the reviewer changed their mind
    client.score(unscored, "note", 1)  # another score doesn't count
    review = reviewed(client, ASK)
    [example] = review.accepted
    trace = client.traces_by_id[kept]
    assert example == Example(
        {"question": "kept", "learner": "learner@example.com", "documents": None},
        {"covered": True, "sources": ["react-2022"], "chunks": ["react-2022:4"]},
        {"type": "factual", "candidate_run": kept, "generated_at": trace.timestamp.isoformat(timespec="microseconds")},
    )
    # a trace that still exists and isn't accepted withdraws its example from later versions
    assert review.withdrawn == {rejected, unscored, changed}


def test_a_score_edited_later_beats_a_score_set_after_it_was_first_set() -> None:
    client = FakeLangfuse()
    [trace_id] = submit(client, ASK, [candidate("q")], {})
    client.score(trace_id, ACCEPTED, 0)  # reviewer A rejects
    client.score(trace_id, ACCEPTED, 0)  # reviewer B rejects later
    client.edit_score(0, 1)  # then A changes their score to accept
    assert [e.inputs["question"] for e in reviewed(client, ASK).accepted] == ["q"]


def test_another_datasets_candidates_are_ignored() -> None:
    client = FakeLangfuse()
    [ours] = submit(client, ASK, [candidate("ours")], {})
    [theirs] = submit(client, INJECTION, [candidate("theirs")], {})
    client.score(ours, ACCEPTED, 1)
    client.score(theirs, ACCEPTED, 1)
    assert [e.inputs["question"] for e in reviewed(client, ASK).accepted] == ["ours"]


def test_accepted_examples_come_oldest_first_whatever_order_they_were_scored_in() -> None:
    client = FakeLangfuse()
    ids = submit(client, ASK, [candidate(f"q{i}") for i in range(130)], {})
    for trace_id in reversed(ids):
        client.score(trace_id, ACCEPTED, 1)
    assert [e.inputs["question"] for e in reviewed(client, ASK).accepted] == [f"q{i}" for i in range(130)]


def test_a_trace_without_generated_at_is_ordered_by_its_timestamp() -> None:
    client = FakeLangfuse()
    [trace_id] = submit(client, ASK, [candidate("kept")], {})
    trace = client.traces_by_id[trace_id]
    client.traces_by_id[trace_id] = replace(trace, metadata={}, timestamp=datetime(2026, 10, 1, tzinfo=UTC))
    client.score(trace_id, ACCEPTED, 1)
    [example] = reviewed(client, ASK).accepted
    assert example.metadata["generated_at"] == "2026-10-01T00:00:00.000000+00:00"


def test_a_deleted_trace_is_neither_accepted_nor_withdrawn() -> None:
    client = FakeLangfuse()
    [trace_id] = submit(client, ASK, [candidate("old")], {})
    client.score(trace_id, ACCEPTED, 1)
    client.delete_trace(trace_id)
    assert reviewed(client, ASK) == Reviewed([], set())


def test_nothing_generated_means_nothing_accepted() -> None:
    assert reviewed(FakeLangfuse(), ASK) == Reviewed([], set())
