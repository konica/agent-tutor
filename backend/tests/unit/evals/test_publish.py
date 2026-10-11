"""Publishing (PRD §10.3 item 6): hand-written plus accepted examples become the next smoke and full versions."""

from collections import Counter

import pytest
from langsmith.utils import LangSmithError

from evals.dataset import Dataset, Example, examples_at
from evals.publish import TYPES, main, split_examples
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


def _accept(client: FakeLangSmith, *questions: str) -> None:
    candidates = [
        Candidate({"question": q}, {"covered": True}, "factual", ({"chunk": "react-2022:1", "text": "t"},))
        for q in questions
    ]
    for run_id in submit(client, ASK, candidates, {}):
        client.create_feedback(run_id, ACCEPTED, score=1)


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
