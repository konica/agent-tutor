"""Eval datasets: hand-written examples in datasets/, split versions made only by publishing (PRD §10.3 item 6)."""

from datetime import timedelta
from pathlib import Path

import pytest
from langsmith.utils import LangSmithError, LangSmithNotFoundError

from evals.corpus import load_manifest
from evals.dataset import (
    Dataset,
    DatasetError,
    Example,
    examples_at,
    load_dataset,
    newest_examples,
    newest_version,
    publish_split,
    version_to_run,
)
from evals.learners import LEARNERS, load_learners
from fakes.langsmith import FakeLangSmith

Q1 = Example({"question": "What is ReAct?", "learner": "learner@example.com", "documents": None}, {"covered": True})
Q2 = Example({"question": "What is CoT?", "learner": "learner@example.com", "documents": None}, {"covered": True})
Q3 = Example({"question": "What is Self-RAG?", "learner": "learner@example.com", "documents": None}, {"covered": False})
ASK = Dataset("ask", "smart-tutor-ask", "", (Q1, Q2))


def _pairs(examples: list) -> list[tuple[str, dict]]:
    return sorted((e.inputs["question"], e.outputs) for e in examples)


def test_the_ask_dataset_asks_eval_learners_about_their_own_seed_documents() -> None:
    ask = load_dataset("ask")
    seeds = load_manifest()
    library = {learner.username: set(learner.documents) for learner in load_learners(LEARNERS, seeds)}
    assert ask.name == "smart-tutor-ask" and 8 <= len(ask.examples) <= 30 and ask.pins == {}
    for example in ask.examples:
        held = library[example.inputs["learner"]]
        assert set(example.inputs["documents"] or []) <= held  # a limit names the learner's own documents
        assert example.outputs["covered"] == bool(example.outputs["sources"])
        assert set(example.outputs["sources"]) <= held
    uncovered = [e for e in ask.examples if not e.outputs["covered"]]
    assert len(uncovered) >= 2
    assert any(e.inputs["documents"] for e in ask.examples if e.outputs["covered"])  # a limited search answered
    assert any(e.inputs["documents"] for e in uncovered)  # and one that doesn't cover the question


def test_a_dataset_without_examples_or_with_an_unknown_pinned_split_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.yaml").write_text("name: x\nexamples: []\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="no examples"):
        load_dataset("x", tmp_path)
    (tmp_path / "y.yaml").write_text(
        "name: y\npins: {nightly: nightly-v1}\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8"
    )
    with pytest.raises(DatasetError, match="nightly"):
        load_dataset("y", tmp_path)


@pytest.mark.parametrize("tag", ["full-v1", "smoke-latest", "smoke-v"])
def test_a_pin_must_name_a_version_of_its_own_split(tmp_path: Path, tag: str) -> None:
    (tmp_path / "w.yaml").write_text(f"name: w\npins: {{smoke: {tag}}}\nexamples: [{{inputs: {{q: a}}}}]\n", "utf-8")
    with pytest.raises(DatasetError, match=f"smoke: {tag}"):
        load_dataset("w", tmp_path)


def test_pins_are_read_from_the_file(tmp_path: Path) -> None:
    (tmp_path / "z.yaml").write_text("name: z\npins: {full: full-v3}\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8")
    assert load_dataset("z", tmp_path).pins == {"full": "full-v3"}


def test_the_first_publish_creates_the_dataset_and_tags_version_1() -> None:
    client = FakeLangSmith()
    assert publish_split(client, ASK, "smoke", [Q1, Q2]) == "smoke-v1"
    assert newest_version(client, "smart-tutor-ask", "smoke") == "smoke-v1"
    examples = examples_at(client, ASK, "smoke", "smoke-v1")
    assert _pairs(examples) == _pairs([Q1, Q2]) and all(e.split == "smoke" for e in examples)


def test_publishing_the_same_examples_again_makes_no_version() -> None:
    client = FakeLangSmith()
    publish_split(client, ASK, "smoke", [Q1, Q2])
    assert publish_split(client, ASK, "smoke", [Q2, Q1]) is None
    assert client.created == 1


def test_a_changed_split_gets_the_next_version_and_the_old_tag_keeps_its_examples() -> None:
    client = FakeLangSmith()
    publish_split(client, ASK, "smoke", [Q1, Q2])
    assert publish_split(client, ASK, "smoke", [Q1, Q2, Q3]) == "smoke-v2"
    assert _pairs(examples_at(client, ASK, "smoke", "smoke-v1")) == _pairs([Q1, Q2])
    assert _pairs(examples_at(client, ASK, "smoke", "smoke-v2")) == _pairs([Q1, Q2, Q3])


def test_splits_are_versioned_apart() -> None:
    client = FakeLangSmith()
    publish_split(client, ASK, "smoke", [Q1])
    assert publish_split(client, ASK, "full", [Q1, Q2]) == "full-v1"
    assert publish_split(client, ASK, "smoke", [Q1, Q3]) == "smoke-v2"
    assert _pairs(examples_at(client, ASK, "full", "full-v1")) == _pairs([Q1, Q2])


def test_example_metadata_is_published() -> None:
    client = FakeLangSmith()
    typed = Example(Q3.inputs, Q3.outputs, {"type": "unanswerable"})
    publish_split(client, ASK, "full", [typed])
    assert [e.metadata for e in examples_at(client, ASK, "full", "full-v1")] == [
        {"type": "unanswerable", "dataset_split": ["full"]}
    ]


def test_the_newest_examples_of_a_split_come_back_with_their_own_metadata() -> None:
    client = FakeLangSmith()
    assert newest_examples(client, ASK, "full") == []  # no dataset yet
    typed = Example(Q3.inputs, Q3.outputs, {"type": "unanswerable", "candidate_run": "r1"})
    publish_split(client, ASK, "smoke", [Q1])
    assert newest_examples(client, ASK, "full") == []  # no full version yet
    publish_split(client, ASK, "full", [Q1])
    publish_split(client, ASK, "full", [Q1, typed])
    assert sorted(newest_examples(client, ASK, "full"), key=lambda e: e.inputs["question"]) == [Q1, typed]


def test_the_runner_uses_the_newest_version_unless_one_is_pinned() -> None:
    client = FakeLangSmith()
    publish_split(client, ASK, "smoke", [Q1])
    publish_split(client, ASK, "smoke", [Q1, Q2])
    assert version_to_run(client, ASK, "smoke") == "smoke-v2"
    pinned = Dataset("ask", "smart-tutor-ask", "", ASK.examples, {"smoke": "smoke-v1"})
    assert version_to_run(client, pinned, "smoke") == "smoke-v1"


def test_a_split_or_dataset_never_published_has_no_version_to_run() -> None:
    client = FakeLangSmith()
    assert version_to_run(client, ASK, "smoke") is None
    publish_split(client, ASK, "smoke", [Q1])
    assert version_to_run(client, ASK, "full") is None


def test_a_pin_to_a_missing_version_stops_the_run() -> None:
    client = FakeLangSmith()
    publish_split(client, ASK, "smoke", [Q1])
    pinned = Dataset("ask", "smart-tutor-ask", "", ASK.examples, {"smoke": "smoke-v7"})
    with pytest.raises(DatasetError, match="smoke-v7"):
        version_to_run(client, pinned, "smoke")


def test_the_fake_refuses_what_langsmith_refuses() -> None:
    # publish_split's tagging relies on these: a tag needs an exact version time, and an unknown tag is not found
    client = FakeLangSmith()
    publish_split(client, ASK, "smoke", [Q1])
    as_of = client.datasets["smart-tutor-ask"].tags["smoke-v1"]
    with pytest.raises(LangSmithError, match="not an exact version"):
        client.update_dataset_tag(dataset_name="smart-tutor-ask", as_of=as_of + timedelta(microseconds=1), tag="x")
    with pytest.raises(LangSmithNotFoundError):
        list(client.list_examples(dataset_name="smart-tutor-ask", splits=["smoke"], as_of="smoke-v2"))


def test_tags_of_other_shapes_are_not_versions() -> None:
    client = FakeLangSmith()
    publish_split(client, ASK, "smoke", [Q1])
    as_of = client.datasets["smart-tutor-ask"].tags["smoke-v1"]
    client.update_dataset_tag(dataset_name="smart-tutor-ask", as_of=as_of, tag="smoke-v10-draft")
    client.update_dataset_tag(dataset_name="smart-tutor-ask", as_of=as_of, tag="smokey-v99")
    assert newest_version(client, "smart-tutor-ask", "smoke") == "smoke-v1"
