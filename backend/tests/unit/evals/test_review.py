"""The human review gate (PRD §10.3 item 6): candidates go to an annotation queue as runs, and only the ones a
reviewer accepted come back as examples."""

from evals.dataset import Dataset, Example
from evals.review import ACCEPTED, Candidate, accepted, candidates_name, ensure_queue, submit
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
    [example] = accepted(client, ASK)
    assert example == Example(
        {"question": "kept", "learner": "learner@example.com", "documents": None},
        {"covered": True, "sources": ["react-2022"], "chunks": ["react-2022:4"]},
        {"type": "factual", "candidate_run": str(kept)},
    )


def test_accepted_examples_come_oldest_first_across_many_feedback_batches() -> None:
    client = FakeLangSmith()
    ids = submit(client, ASK, [candidate(f"q{i}") for i in range(130)], {})
    for run_id in reversed(ids):
        client.create_feedback(run_id, ACCEPTED, score=1)
    assert [e.inputs["question"] for e in accepted(client, ASK)] == [f"q{i}" for i in range(130)]


def test_no_candidates_project_means_nothing_accepted() -> None:
    assert accepted(FakeLangSmith(), ASK) == []
