"""The human review gate (PRD §10.3 item 6): candidates go to an annotation queue as runs, and only the ones a
reviewer accepted come back as examples."""

from dataclasses import replace

import pytest
from langsmith.utils import LangSmithNotFoundError

from evals.dataset import Dataset, Example
from evals.review import ACCEPTED, Candidate, Reviewed, candidates_name, ensure_queue, reviewed, submit
from fakes.langsmith import FakeLangSmith

ASK = Dataset("ask", "smart-tutor-ask", "", (Example({"question": "hand"}, {"covered": True}),))


def candidate(question: str, kind: str = "factual", covered: bool = True) -> Candidate:
    return Candidate(
        inputs={"question": question, "learner": "learner@example.com", "documents": None},
        expected={"covered": covered, "sources": ["react-2022"] if covered else [], "chunks": ["react-2022:4"]},
        type=kind,
        evidence=({"chunk": "react-2022:4", "text": "ReAct interleaves reasoning and acting."},),
    )


def test_the_queue_is_created_once_with_a_required_accepted_rubric_item() -> None:
    client = FakeLangSmith()
    first, again = ensure_queue(client, ASK), ensure_queue(client, ASK)
    assert first == again and len(client.queues) == 1
    queue = client.queues[first]
    assert queue.name == candidates_name(ASK) == "smart-tutor-ask-candidates"
    assert [(i["feedback_key"], i["is_required"]) for i in queue.rubric_items] == [(ACCEPTED, True)]
    assert client.feedback_configs[ACCEPTED]["type"] == "continuous"
    assert "reject" in (queue.rubric_instructions or "").lower()


def test_submitted_candidates_are_runs_in_the_queue_with_their_evidence() -> None:
    client = FakeLangSmith()
    ids = submit(client, ASK, [candidate("What is ReAct?"), candidate("Is X?", "unanswerable", False)], {"batch": "b1"})
    assert client.flushed >= 1
    queue = next(iter(client.queues.values()))
    assert queue.run_ids == ids
    run = client.runs[ids[1]]
    assert run.project_name == "smart-tutor-ask-candidates" and run.name == "ask-candidate"
    assert run.inputs["question"] == "Is X?"
    assert run.outputs == {
        "expected": {"covered": False, "sources": [], "chunks": ["react-2022:4"]},
        "type": "unanswerable",
        "evidence": [{"chunk": "react-2022:4", "text": "ReAct interleaves reasoning and acting."}],
    }
    assert run.extra == {"metadata": {"dataset": "smart-tutor-ask", "type": "unanswerable", "batch": "b1"}}


def test_runs_are_queued_by_their_full_key_in_the_candidates_project() -> None:
    client = FakeLangSmith()
    ids = submit(client, ASK, [candidate("a"), candidate("b")], {})
    project = client.read_project(project_name="smart-tutor-ask-candidates")
    [keys] = client.queue_adds
    assert keys == [
        {"run_id": run_id, "session_id": project.id, "start_time": client.runs[run_id].start_time} for run_id in ids
    ]
    assert project.description and "smart-tutor-ask" in project.description


def test_an_existing_candidates_project_is_reused() -> None:
    client = FakeLangSmith()
    first = submit(client, ASK, [candidate("a")], {})
    second = submit(client, ASK, [candidate("b")], {})
    assert len(client.projects) == 1
    assert next(iter(client.queues.values())).run_ids == [*first, *second]


def test_runs_not_yet_ingested_are_queued_after_retries() -> None:
    client, sleeps = FakeLangSmith(), []
    client.ingestion_lag = 2
    ids = submit(client, ASK, [candidate("a")], {}, sleep=sleeps.append)
    assert next(iter(client.queues.values())).run_ids == ids
    assert sleeps == [2, 4]


def test_many_candidates_are_queued_in_batches_of_at_most_100() -> None:
    client = FakeLangSmith()
    ids = submit(client, ASK, [candidate(f"q{i}") for i in range(130)], {})
    assert [len(keys) for keys in client.queue_adds] == [100, 30]
    assert next(iter(client.queues.values())).run_ids == ids


def test_runs_still_missing_after_about_two_minutes_raise() -> None:
    client, sleeps = FakeLangSmith(), []
    client.ingestion_lag = 1000
    with pytest.raises(LangSmithNotFoundError):
        submit(client, ASK, [candidate("a")], {}, sleep=sleeps.append)
    assert sleeps[:3] == [2, 4, 8] and max(sleeps) <= 15 and 100 <= sum(sleeps) <= 150


def test_only_items_whose_latest_feedback_accepts_them_are_accepted() -> None:
    client = FakeLangSmith()
    kept, rejected, unscored, changed = submit(
        client, ASK, [candidate("kept"), candidate("rejected"), candidate("unscored"), candidate("changed")], {}
    )
    client.create_feedback(kept, ACCEPTED, score=1)
    client.create_feedback(rejected, ACCEPTED, score=0)
    client.create_feedback(changed, ACCEPTED, score=1)
    client.create_feedback(changed, ACCEPTED, score=0)  # the reviewer changed their mind
    client.create_feedback(unscored, "note", score=1)  # another key doesn't count
    review = reviewed(client, ASK)
    [example] = review.accepted
    assert example == Example(
        {"question": "kept", "learner": "learner@example.com", "documents": None},
        {"covered": True, "sources": ["react-2022"], "chunks": ["react-2022:4"]},
        {
            "type": "factual",
            "candidate_run": str(kept),
            "generated_at": client.runs[kept].start_time.isoformat(timespec="microseconds"),
        },
    )
    # a run that still exists and isn't accepted withdraws its example from later versions
    assert review.withdrawn == {str(rejected), str(unscored), str(changed)}


def test_a_naive_run_start_time_is_read_as_utc() -> None:
    client = FakeLangSmith()
    [run_id] = submit(client, ASK, [candidate("kept")], {})
    client.create_feedback(run_id, ACCEPTED, score=1)
    aware = client.runs[run_id].start_time
    client.runs[run_id] = replace(client.runs[run_id], start_time=aware.replace(tzinfo=None))
    [example] = reviewed(client, ASK).accepted
    assert example.metadata["generated_at"] == aware.isoformat(timespec="microseconds")


def test_accepted_examples_come_oldest_first_across_many_feedback_batches() -> None:
    client = FakeLangSmith()
    ids = submit(client, ASK, [candidate(f"q{i}") for i in range(130)], {})
    for run_id in reversed(ids):
        client.create_feedback(run_id, ACCEPTED, score=1)
    assert [e.inputs["question"] for e in reviewed(client, ASK).accepted] == [f"q{i}" for i in range(130)]


def test_an_expired_run_is_neither_accepted_nor_withdrawn() -> None:
    client = FakeLangSmith()
    [run_id] = submit(client, ASK, [candidate("old")], {})
    client.create_feedback(run_id, ACCEPTED, score=1)
    del client.runs[run_id]  # the project's trace retention deleted it
    assert reviewed(client, ASK) == Reviewed([], set())


def test_no_candidates_project_means_nothing_accepted() -> None:
    assert reviewed(FakeLangSmith(), ASK) == Reviewed([], set())
