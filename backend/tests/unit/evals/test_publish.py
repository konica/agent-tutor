"""Publishing (PRD §10.3 item 6): hand-written plus accepted examples become the next smoke and full versions in
Langfuse. Accepted candidates are read from the dataset's annotation queue in the same Langfuse project."""

from collections import Counter

import pytest

from evals.dataset import Dataset, Example, examples_at, in_eval_share, publish_split
from evals.langfuse_client import KEYS, URLS, LangfuseError, Trace
from evals.publish import TYPES, _summary, main, oldest_first, split_examples
from evals.review import ACCEPTED, Candidate, submit
from fakes.langfuse import FakeLangfuse

HAND = (Example({"question": "hand"}, {"covered": True}),)
ASK = Dataset("ask", "smart-tutor-ask", "", HAND)


def generated(question: str, kind: str) -> Example:
    return Example({"question": question}, {"covered": True}, {"type": kind, "candidate_run": question})


def test_full_holds_every_accepted_item_and_smoke_a_balanced_share_up_to_its_size() -> None:
    items = [generated(f"{kind}-{i}", kind) for kind in TYPES for i in range(10)]
    splits = split_examples(ASK, items, smoke_size=17)
    assert splits["full"] == [*HAND, *items]
    assert len(splits["smoke"]) == 17 and splits["smoke"][0] == HAND[0]
    assert Counter(e.metadata["type"] for e in splits["smoke"][1:]) == {kind: 2 for kind in TYPES}
    assert set(map(id, splits["smoke"])) <= set(map(id, splits["full"]))


def test_smoke_takes_the_oldest_accepted_items_of_each_type_first() -> None:
    items = [generated("f1", "factual"), generated("f2", "factual"), generated("u1", "unanswerable")]
    smoke = split_examples(ASK, items, smoke_size=3)["smoke"]
    assert [e.inputs["question"] for e in smoke] == ["hand", "f1", "u1"]


def test_an_accepted_item_equal_to_a_hand_written_one_is_not_added_twice() -> None:
    duplicate = Example({"question": "hand"}, {"covered": True}, {"type": "factual", "candidate_run": "x"})
    assert split_examples(ASK, [duplicate])["full"] == list(HAND)


class Stores:
    """Langfuse: the review queue and the datasets."""

    def __init__(self) -> None:
        self.langfuse = FakeLangfuse()

    def submit(self, *questions: str) -> list[str]:
        candidates = [
            Candidate({"question": q}, {"covered": True}, "factual", ({"chunk": "react-2022:1", "text": "t"},))
            for q in questions
        ]
        return submit(self.langfuse, ASK, candidates, {})

    def accept(self, *questions: str) -> list[str]:
        ids = self.submit(*questions)
        for trace_id in ids:
            self.langfuse.score(trace_id, ACCEPTED, 1)
        return ids

    def publish(self, *argv: str, dataset: Dataset = ASK) -> int:
        return main(list(argv), client=self.langfuse, load=lambda key: dataset, keys=[dataset.key])

    def questions(self, version: str) -> list[str]:
        return [e.inputs["question"] for e in examples_at(self.langfuse, ASK, version)]


def test_an_accepted_example_stays_after_its_candidate_trace_is_deleted(capsys: pytest.CaptureFixture[str]) -> None:
    stores = Stores()
    [old] = stores.accept("old")
    assert stores.publish() == 0
    capsys.readouterr()
    stores.langfuse.delete_trace(old)
    stores.publish()
    assert capsys.readouterr().out.count("unchanged") == 2  # no smaller version
    stores.accept("new")
    stores.publish()
    assert sorted(stores.questions("full-v2")) == ["hand", "new", "old"]
    assert sorted(stores.questions("smoke-v2")) == ["hand", "new", "old"]
    [carried] = [e for e in examples_at(stores.langfuse, ASK, "full-v2") if e.inputs["question"] == "old"]
    assert carried.metadata["candidate_run"] == old


def test_a_carried_example_a_reviewer_rejects_later_is_dropped() -> None:
    stores = Stores()
    changed, _ = stores.accept("changed", "kept")
    stores.publish()
    stores.langfuse.score(changed, ACCEPTED, 0)
    stores.publish()
    assert sorted(stores.questions("full-v2")) == ["hand", "kept"]
    assert sorted(stores.questions("smoke-v2")) == ["hand", "kept"]


def test_a_later_publish_adds_new_acceptances_and_keeps_smoke_oldest_first() -> None:
    stores = Stores()
    older, newer = stores.submit("older", "newer")
    stores.langfuse.score(newer, ACCEPTED, 1)
    stores.publish()
    stores.langfuse.score(older, ACCEPTED, 1)  # accepted after a newer candidate was published
    stores.publish()
    assert stores.questions("full-v2") == ["hand", "older", "newer"]
    assert stores.questions("smoke-v2") == ["hand", "older", "newer"]


def test_generated_examples_are_ordered_by_when_they_were_generated() -> None:
    def made(question: str, at: str | None, run: str) -> Example:
        metadata = {"candidate_run": run} | ({"generated_at": at} if at else {})
        return Example({"question": question}, {"covered": True}, metadata)

    examples = [made("b", "2026-10-02T00:00:00.000000+00:00", "1"), made("a", None, "9"), made("c", "2026-10-01", "2")]
    examples += [made("d", "2026-10-02T00:00:00.000000+00:00", "0")]
    assert [e.inputs["question"] for e in oldest_first(examples)] == ["a", "c", "d", "b"]


def test_publish_makes_the_next_versions_in_langfuse_and_prints_them(capsys: pytest.CaptureFixture[str]) -> None:
    stores = Stores()
    stores.accept("What is ReAct?")
    assert stores.publish() == 0
    out = capsys.readouterr().out
    assert "published smart-tutor-ask/smoke-v1" in out and "published smart-tutor-ask/full-v1" in out
    assert sorted(stores.questions("full-v1")) == ["What is ReAct?", "hand"]


def test_a_second_publish_with_nothing_new_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    stores = Stores()
    stores.accept("What is ReAct?")
    stores.publish()
    assert stores.publish() == 0
    assert "unchanged" in capsys.readouterr().out
    assert set(stores.langfuse.datasets) == {"smart-tutor-ask/smoke-v1", "smart-tutor-ask/full-v1"}


def test_a_dry_run_prints_the_splits_and_publishes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    stores = Stores()
    stores.accept("What is ReAct?")
    assert stores.publish("--dry-run") == 0
    assert stores.langfuse.datasets == {}
    assert "factual" in capsys.readouterr().out


def test_types_missing_from_smoke_are_named(capsys: pytest.CaptureFixture[str]) -> None:
    stores = Stores()
    stores.accept("What is ReAct?")
    stores.publish()
    assert "no accepted drift" in capsys.readouterr().out


def test_a_review_queue_error_exits_1_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    class NoKey(FakeLangfuse):
        def traces(self, name: str) -> list[Trace]:
            raise LangfuseError("401: Invalid credentials")

    stores = Stores()
    stores.langfuse = NoKey()
    assert stores.publish() == 1
    err = capsys.readouterr().err
    assert "Can't reach Langfuse: 401: Invalid credentials" in err and all(key in err for key in KEYS)


def test_a_langfuse_error_exits_1_naming_the_keys_and_the_hours(capsys: pytest.CaptureFixture[str]) -> None:
    class Off(FakeLangfuse):
        def dataset_names(self) -> list[str]:
            raise LangfuseError("[Errno 111] Connection refused")

    stores = Stores()
    stores.langfuse = Off()
    assert stores.publish() == 1
    err = capsys.readouterr().err
    assert "Can't reach Langfuse: [Errno 111] Connection refused" in err
    assert all(key in err for key in KEYS) and "18:00-07:00" in err


def test_without_langfuse_keys_publish_exits_1_and_says_which(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in (*KEYS, *URLS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    assert main([], load=lambda key: ASK, keys=["ask"]) == 1
    assert "LANGFUSE_SECRET_KEY not set" in capsys.readouterr().err


def test_a_dataset_with_an_eval_share_publishes_only_its_held_out_questions() -> None:
    stores = Stores()
    shared = Dataset("ask", "smart-tutor-ask", "", HAND, eval_share=0.3)
    questions = [f"question {i}" for i in range(40)]
    stores.accept(*questions)
    assert stores.publish(dataset=shared) == 0
    full = {e.inputs["question"] for e in examples_at(stores.langfuse, shared, "full-v1")}
    assert full == {"hand"} | {q for q in questions if in_eval_share(q, 0.3)}
    assert 1 < len(full) < 41


FULL_ONLY = Dataset("full-only", "smart-tutor-full-only", "", HAND, splits=("full",))


def test_a_dataset_that_opts_out_of_smoke_is_split_and_published_to_full_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert set(split_examples(FULL_ONLY, [])) == {"full"}
    stores = Stores()
    assert stores.publish(dataset=FULL_ONLY) == 0
    out = capsys.readouterr().out
    assert "full-v1" in out and "smoke" not in out
    assert set(stores.langfuse.datasets) == {"smart-tutor-full-only/full-v1"}


def test_publish_split_new_version_when_only_metadata_changes() -> None:
    client = FakeLangfuse()
    labelled = Example(HAND[0].inputs, HAND[0].outputs, {"category": "single_hop"})
    relabelled = Example(HAND[0].inputs, HAND[0].outputs, {"category": "multi_hop"})
    assert publish_split(client, ASK, "full", [labelled]) == "full-v1"
    assert publish_split(client, ASK, "full", [labelled]) is None
    assert publish_split(client, ASK, "full", [relabelled]) == "full-v2"


def test_split_examples_honours_row_splits() -> None:
    full_only = Example({"question": "gold"}, {"covered": True}, {"category": "single_hop"}, ("full",))
    dataset = Dataset("ask", "smart-tutor-ask", "", (*HAND, full_only))
    items = [generated(f"factual-{i}", "factual") for i in range(3)]
    splits = split_examples(dataset, items, smoke_size=2)
    assert full_only in splits["full"] and full_only not in splits["smoke"]
    assert splits["smoke"] == [HAND[0], items[0]]  # the full-only row doesn't count toward the smoke size


def test_summary_counts_gold_rows_as_hand_written() -> None:
    gold = Example({"question": "g"}, {}, {"category": "single_hop", "type": "factual"})
    assert _summary([gold, generated("q", "factual")]) == "1 factual, 1 hand-written"
