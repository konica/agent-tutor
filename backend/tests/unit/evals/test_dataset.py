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
    in_eval_share,
    load_dataset,
    newest_examples,
    newest_version,
    normalized,
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


def test_the_ask_dataset_has_multi_turn_conversations_of_every_kind_naming_seed_documents() -> None:
    manifest = load_manifest()
    examples = load_dataset("ask").examples
    with_history = [e for e in examples if "history" in e.inputs]
    for e in with_history:
        history = e.inputs["history"]
        assert isinstance(history, list) and history
        assert all(isinstance(turn, str) and turn.strip() for turn in history)
    for e in examples:
        assert set(e.inputs.get("documents") or []) <= set(manifest)
        assert set(e.outputs.get("sources") or []) <= set(manifest)
    assert len(with_history) >= 10
    kinds = {(e.inputs["documents"] is not None, e.outputs["covered"]) for e in with_history}
    assert {(True, False), (False, True), (True, True)} <= kinds


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


KINDS = {
    "subject_concept",
    "document_question",
    "follow_up",
    "study_task",
    "greeting",
    "entertainment",
    "personal_task",
    "live_information",
    "borderline_study_task",
    "borderline_personal_task",
    "library_news",
    "live_news",
}


def test_the_topic_check_dataset_labels_both_sides_and_holds_out_a_share() -> None:
    dataset = load_dataset("topic_check")
    assert dataset.name == "smart-tutor-topic-check" and dataset.eval_share == 0.3
    assert all(isinstance(e.outputs["off_topic"], bool) and e.outputs["kind"] in KINDS for e in dataset.examples)
    assert sum(not e.outputs["off_topic"] for e in dataset.examples) >= 15
    assert sum(e.outputs["off_topic"] for e in dataset.examples) >= 12
    follow_ups = [e for e in dataset.examples if e.outputs["kind"] == "follow_up"]
    assert follow_ups and all(e.inputs["history"][-1]["question"] for e in follow_ups)


def test_an_eval_share_outside_0_and_1_is_refused(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text("name: s\neval_share: 1.5\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="eval_share"):
        load_dataset("s", tmp_path)


def test_the_held_out_share_is_stable_ignores_case_and_spacing_and_is_about_its_size() -> None:
    assert normalized("  What IS  attention? ") == "what is attention?"
    assert in_eval_share("What is attention?", 0.3) == in_eval_share("what is   ATTENTION?", 0.3)
    held = sum(in_eval_share(f"question number {i}", 0.3) for i in range(4000))
    assert 0.27 < held / 4000 < 0.33


def test_two_fixed_questions_keep_their_side_of_the_split() -> None:
    # Changing the hash or the normalization moves examples between training and evaluation: do it on purpose.
    assert in_eval_share("Explain how a hash map works.", 0.3) is True
    assert in_eval_share("What is a covalent bond?", 0.3) is False


def test_a_dataset_is_in_both_splits_unless_its_file_lists_some(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("name: a\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("name: b\nsplits: [full]\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8")
    assert load_dataset("a", tmp_path).splits == ("smoke", "full")
    assert load_dataset("b", tmp_path).splits == ("full",)


def test_a_dataset_naming_an_unknown_split_or_pinning_one_it_opts_out_of_is_refused(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("name: c\nsplits: [nightly]\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="nightly"):
        load_dataset("c", tmp_path)
    (tmp_path / "d.yaml").write_text(
        "name: d\nsplits: [full]\npins: {smoke: smoke-v1}\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8"
    )
    with pytest.raises(DatasetError, match="opts out"):
        load_dataset("d", tmp_path)
