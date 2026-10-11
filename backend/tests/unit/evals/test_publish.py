"""Publishing (PRD §10.3 item 6): hand-written plus accepted examples become the next smoke and full versions."""

import uuid
from collections import Counter

import pytest
from langsmith.utils import LangSmithError

from evals.dataset import Dataset, Example, examples_at
from evals.publish import TYPES, main, oldest_first, split_examples
from evals.review import ACCEPTED, Candidate, submit
from fakes.langsmith import FakeLangSmith

HAND = (Example({"question": "hand"}, {"covered": True}),)
ASK = Dataset("ask", "smart-tutor-ask", "", HAND)


def generated(question: str, kind: str) -> Example:
    return Example({"question": question}, {"covered": True}, {"type": kind, "candidate_run": question})


def test_full_holds_every_accepted_item_and_smoke_a_balanced_share_up_to_its_size() -> None:
    items = [generated(f"{kind}-{i}", kind) for kind in TYPES for i in range(10)]
    splits = split_examples(ASK, items, smoke_size=13)
    assert splits["full"] == [*HAND, *items]
    assert len(splits["smoke"]) == 13 and splits["smoke"][0] == HAND[0]
    assert Counter(e.metadata["type"] for e in splits["smoke"][1:]) == {kind: 2 for kind in TYPES}
    assert set(map(id, splits["smoke"])) <= set(map(id, splits["full"]))


def test_smoke_takes_the_oldest_accepted_items_of_each_type_first() -> None:
    items = [generated("f1", "factual"), generated("f2", "factual"), generated("u1", "unanswerable")]
    smoke = split_examples(ASK, items, smoke_size=3)["smoke"]
    assert [e.inputs["question"] for e in smoke] == ["hand", "f1", "u1"]


def test_an_accepted_item_equal_to_a_hand_written_one_is_not_added_twice() -> None:
    duplicate = Example({"question": "hand"}, {"covered": True}, {"type": "factual", "candidate_run": "x"})
    assert split_examples(ASK, [duplicate])["full"] == list(HAND)


def _submit(client: FakeLangSmith, *questions: str) -> list[uuid.UUID]:
    candidates = [
        Candidate({"question": q}, {"covered": True}, "factual", ({"chunk": "react-2022:1", "text": "t"},))
        for q in questions
    ]
    return submit(client, ASK, candidates, {})


def _accept(client: FakeLangSmith, *questions: str) -> list[uuid.UUID]:
    ids = _submit(client, *questions)
    for run_id in ids:
        client.create_feedback(run_id, ACCEPTED, score=1)
    return ids


def _expire(client: FakeLangSmith, run_id: uuid.UUID) -> None:
    """The candidates project's trace retention deletes a run and its feedback."""
    del client.runs[run_id]
    client.feedback = [f for f in client.feedback if f.run_id != run_id]


def _publish(client: FakeLangSmith) -> None:
    assert main([], client=client, load=lambda key: ASK, keys=["ask"]) == 0


def _questions(client: FakeLangSmith, split: str, version: str) -> list[str]:
    return [e.inputs["question"] for e in examples_at(client, ASK, split, version)]


def test_an_accepted_example_stays_after_its_candidate_run_expires(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
    [old] = _accept(client, "old")
    _publish(client)
    capsys.readouterr()
    _expire(client, old)
    _publish(client)
    assert capsys.readouterr().out.count("unchanged") == 2  # no smaller version
    _accept(client, "new")
    _publish(client)
    assert sorted(_questions(client, "full", "full-v2")) == ["hand", "new", "old"]
    assert sorted(_questions(client, "smoke", "smoke-v2")) == ["hand", "new", "old"]
    [carried] = [e for e in examples_at(client, ASK, "full", "full-v2") if e.inputs["question"] == "old"]
    assert carried.metadata is not None and carried.metadata["candidate_run"] == str(old)


def test_a_carried_example_a_reviewer_rejects_later_is_dropped() -> None:
    client = FakeLangSmith()
    changed, _ = _accept(client, "changed", "kept")
    _publish(client)
    client.create_feedback(changed, ACCEPTED, score=0)
    _publish(client)
    assert sorted(_questions(client, "full", "full-v2")) == ["hand", "kept"]
    assert sorted(_questions(client, "smoke", "smoke-v2")) == ["hand", "kept"]


def test_a_later_publish_adds_new_acceptances_and_keeps_smoke_oldest_first() -> None:
    client = FakeLangSmith()
    older, newer = _submit(client, "older", "newer")
    client.create_feedback(newer, ACCEPTED, score=1)
    _publish(client)
    client.create_feedback(older, ACCEPTED, score=1)  # accepted after a newer candidate was published
    _publish(client)
    assert _questions(client, "full", "full-v2") == ["hand", "older", "newer"]
    assert _questions(client, "smoke", "smoke-v2") == ["hand", "older", "newer"]


def test_generated_examples_are_ordered_by_when_they_were_generated() -> None:
    def made(question: str, at: str | None, run: str) -> Example:
        metadata = {"candidate_run": run} | ({"generated_at": at} if at else {})
        return Example({"question": question}, {"covered": True}, metadata)

    examples = [made("b", "2026-10-02T00:00:00.000000+00:00", "1"), made("a", None, "9"), made("c", "2026-10-01", "2")]
    examples += [made("d", "2026-10-02T00:00:00.000000+00:00", "0")]
    assert [e.inputs["question"] for e in oldest_first(examples)] == ["a", "c", "d", "b"]


def test_publish_makes_the_next_versions_and_prints_them(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
    _accept(client, "What is ReAct?")
    assert main([], client=client, load=lambda key: ASK, keys=["ask"]) == 0
    out = capsys.readouterr().out
    assert "smoke-v1" in out and "full-v1" in out
    questions = sorted(e.inputs["question"] for e in examples_at(client, ASK, "full", "full-v1"))
    assert questions == ["What is ReAct?", "hand"]


def test_a_second_publish_with_nothing_new_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
    _accept(client, "What is ReAct?")
    main([], client=client, load=lambda key: ASK, keys=["ask"])
    assert main([], client=client, load=lambda key: ASK, keys=["ask"]) == 0
    assert "unchanged" in capsys.readouterr().out
    assert client.datasets["smart-tutor-ask"].tags.keys() == {"smoke-v1", "full-v1"}


def test_a_dry_run_prints_the_splits_and_publishes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
    _accept(client, "What is ReAct?")
    assert main(["--dry-run"], client=client, load=lambda key: ASK, keys=["ask"]) == 0
    assert "smart-tutor-ask" not in client.datasets
    assert "factual" in capsys.readouterr().out


def test_types_missing_from_smoke_are_named(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
    _accept(client, "What is ReAct?")
    main([], client=client, load=lambda key: ASK, keys=["ask"])
    assert "no accepted drift" in capsys.readouterr().out


def test_a_langsmith_error_exits_1_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    class NoKey(FakeLangSmith):
        def list_runs(self, **kwargs: object) -> object:
            raise LangSmithError("Authentication failed")

    assert main([], client=NoKey(), load=lambda key: ASK, keys=["ask"]) == 1
    assert "LANGSMITH_API_KEY" in capsys.readouterr().err
