"""Eval datasets: hand-written examples in datasets/, split versions made only by publishing, each a Langfuse dataset
(PRD §10.3 item 6)."""

import ast
from pathlib import Path

import pytest

import evals as evals_package
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
from evals.langfuse_client import Item, LangfuseError
from evals.learners import LEARNERS, load_learners
from fakes.langfuse import FakeLangfuse

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


def test_the_first_publish_makes_version_1_as_a_langfuse_dataset_of_its_own() -> None:
    client = FakeLangfuse()
    assert publish_split(client, ASK, "smoke", [Q1, Q2]) == "smoke-v1"
    assert list(client.datasets) == ["smart-tutor-ask/smoke-v1"]
    assert client.datasets["smart-tutor-ask/smoke-v1"].metadata == {"split": "smoke", "examples": 2}
    assert newest_version(client, ASK, "smoke") == "smoke-v1"
    assert _pairs(examples_at(client, ASK, "smoke-v1")) == _pairs([Q1, Q2])


def test_publishing_the_same_examples_again_makes_no_version() -> None:
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1, Q2])
    assert publish_split(client, ASK, "smoke", [Q2, Q1]) is None
    assert list(client.datasets) == ["smart-tutor-ask/smoke-v1"]


def test_a_changed_split_gets_the_next_version_and_the_old_one_keeps_its_examples() -> None:
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1, Q2])
    assert publish_split(client, ASK, "smoke", [Q1, Q2, Q3]) == "smoke-v2"
    assert _pairs(examples_at(client, ASK, "smoke-v1")) == _pairs([Q1, Q2])
    assert _pairs(examples_at(client, ASK, "smoke-v2")) == _pairs([Q1, Q2, Q3])


def test_splits_are_versioned_apart() -> None:
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1])
    assert publish_split(client, ASK, "full", [Q1, Q2]) == "full-v1"
    assert publish_split(client, ASK, "smoke", [Q1, Q3]) == "smoke-v2"
    assert _pairs(examples_at(client, ASK, "full-v1")) == _pairs([Q1, Q2])


def test_example_metadata_is_published_and_read_back() -> None:
    client = FakeLangfuse()
    typed = Example(Q3.inputs, Q3.outputs, {"type": "unanswerable"})
    publish_split(client, ASK, "full", [typed])
    assert [e.metadata for e in examples_at(client, ASK, "full-v1")] == [{"type": "unanswerable"}]


def test_the_newest_examples_of_a_split_come_back_with_their_own_metadata() -> None:
    client = FakeLangfuse()
    assert newest_examples(client, ASK, "full") == []  # nothing published yet
    typed = Example(Q3.inputs, Q3.outputs, {"type": "unanswerable", "candidate_run": "r1"})
    publish_split(client, ASK, "smoke", [Q1])
    assert newest_examples(client, ASK, "full") == []  # no full version yet
    publish_split(client, ASK, "full", [Q1])
    publish_split(client, ASK, "full", [Q1, typed])
    assert sorted(newest_examples(client, ASK, "full"), key=lambda e: e.inputs["question"]) == [Q1, typed]


def test_the_runner_uses_the_newest_version_unless_one_is_pinned() -> None:
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1])
    publish_split(client, ASK, "smoke", [Q1, Q2])
    assert version_to_run(client, ASK, "smoke") == "smoke-v2"
    pinned = Dataset("ask", "smart-tutor-ask", "", ASK.examples, {"smoke": "smoke-v1"})
    assert version_to_run(client, pinned, "smoke") == "smoke-v1"
    assert _pairs(examples_at(client, pinned, "smoke-v1")) == _pairs([Q1])


def test_a_split_or_dataset_never_published_has_no_version_to_run() -> None:
    client = FakeLangfuse()
    assert version_to_run(client, ASK, "smoke") is None
    publish_split(client, ASK, "smoke", [Q1])
    assert version_to_run(client, ASK, "full") is None


def test_a_pin_to_a_missing_version_stops_the_run() -> None:
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1])
    pinned = Dataset("ask", "smart-tutor-ask", "", ASK.examples, {"smoke": "smoke-v7"})
    with pytest.raises(DatasetError, match="smoke-v7"):
        version_to_run(client, pinned, "smoke")
    with pytest.raises(DatasetError, match="smoke-v7"):
        examples_at(client, pinned, "smoke-v7")


def _stopped_part_way(client: FakeLangfuse, tag: str, *examples: Example) -> None:
    """A publish that created the version's dataset and then failed after some of its items."""
    name = f"smart-tutor-ask/{tag}"
    client.create_dataset(name, description="", metadata={"split": tag.split("-")[0], "examples": len(examples) + 1})
    for e in examples:
        client.create_item(name, Item(e.inputs, e.outputs, e.metadata))


def test_an_incomplete_version_is_never_the_newest_and_its_number_is_not_reused() -> None:
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1])
    _stopped_part_way(client, "smoke-v2", Q1)
    assert newest_version(client, ASK, "smoke") == "smoke-v1"
    assert _pairs(newest_examples(client, ASK, "smoke")) == _pairs([Q1])
    assert publish_split(client, ASK, "smoke", [Q1]) is None  # equal to the newest complete version
    assert publish_split(client, ASK, "smoke", [Q1, Q2]) == "smoke-v3"
    pinned = Dataset("ask", "smart-tutor-ask", "", ASK.examples, {"smoke": "smoke-v2"})
    with pytest.raises(DatasetError, match="smoke-v2 is incomplete"):
        version_to_run(client, pinned, "smoke")


def test_datasets_of_other_shapes_or_folders_are_not_versions() -> None:
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1])
    for name in ("smart-tutor-ask/smoke-v10-draft", "smart-tutor-ask/smokey-v99", "smart-tutor-asked/smoke-v9"):
        client.create_dataset(name, description="", metadata={"examples": 0})
    assert newest_version(client, ASK, "smoke") == "smoke-v1"
    assert publish_split(client, ASK, "smoke", [Q2]) == "smoke-v2"


def _imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    return {name.split(".")[0] for name in found} | {
        n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }


def test_only_the_review_queue_imports_langsmith_and_only_the_seam_imports_the_langfuse_sdk() -> None:
    evals = Path(evals_package.__file__).parent
    modules = list(evals.rglob("*.py"))
    # the annotation queue is LangSmith's until #319; datasets, the runner, and the evaluators are on Langfuse
    assert {p.relative_to(evals).as_posix() for p in modules if "langsmith" in _imported(p)} == {
        "generate.py",
        "review.py",
    }
    assert {p.relative_to(evals).as_posix() for p in modules if "langfuse" in _imported(p)} == {"langfuse_client.py"}


def test_the_fake_refuses_to_overwrite_a_dataset_or_fill_a_missing_one() -> None:
    # publishing relies on never writing into a version that exists
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", [Q1])
    with pytest.raises(LangfuseError, match="exists"):
        client.create_dataset("smart-tutor-ask/smoke-v1", description="", metadata={})
    with pytest.raises(LangfuseError, match="no dataset"):
        client.create_item("smart-tutor-ask/smoke-v9", Item({}, {}))


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
