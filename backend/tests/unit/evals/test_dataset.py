"""Hand-written eval datasets: loaded from datasets/, pushed to LangSmith once per version (PRD §10.3 item 6)."""

from pathlib import Path

import pytest

from evals.corpus import load_manifest
from evals.dataset import Dataset, DatasetError, Example, Split, load_dataset, versioned_examples
from evals.learners import LEARNERS, load_learners
from fakes.langsmith import FakeLangSmith

Q1 = Example({"question": "What is ReAct?", "learner": "learner@example.com", "documents": None}, {"covered": True})
Q2 = Example({"question": "What is CoT?", "learner": "learner@example.com", "documents": None}, {"covered": True})


def _dataset(*examples: Example, version: str = "smoke-v1") -> Dataset:
    return Dataset("ask", "smart-tutor-ask", "", {"smoke": Split("smoke", version, examples)})


def _pairs(examples: list) -> list[tuple[str, dict]]:
    return sorted((e.inputs["question"], e.outputs) for e in examples)


def test_the_ask_smoke_split_asks_eval_learners_about_their_own_seed_documents() -> None:
    smoke = load_dataset("ask").splits["smoke"]
    seeds = load_manifest()
    library = {learner.username: set(learner.documents) for learner in load_learners(LEARNERS, seeds)}
    assert smoke.version == "smoke-v1" and 8 <= len(smoke.examples) <= 30
    for example in smoke.examples:
        held = library[example.inputs["learner"]]
        assert set(example.inputs["documents"] or []) <= held  # a limit names the learner's own documents
        assert example.outputs["covered"] == bool(example.outputs["sources"])
        assert set(example.outputs["sources"]) <= held
    uncovered = [e for e in smoke.examples if not e.outputs["covered"]]
    assert len(uncovered) >= 2
    assert any(e.inputs["documents"] for e in smoke.examples if e.outputs["covered"])  # a limited search answered
    assert any(e.inputs["documents"] for e in uncovered)  # and one that doesn't cover the question


def test_a_split_without_a_version_or_examples_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.yaml").write_text("name: x\nsplits:\n  smoke:\n    examples: [{inputs: {q: a}}]\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="version"):
        load_dataset("x", tmp_path)
    (tmp_path / "y.yaml").write_text("name: y\nsplits:\n  smoke: {version: v1, examples: []}\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="no examples"):
        load_dataset("y", tmp_path)


def test_the_first_run_of_a_version_creates_the_dataset_pushes_the_split_and_tags_it() -> None:
    client, dataset = FakeLangSmith(), _dataset(Q1, Q2)
    examples = versioned_examples(client, dataset, dataset.splits["smoke"])
    assert _pairs(examples) == _pairs([Q1, Q2])
    assert all(e.split == "smoke" for e in examples)
    assert "smoke-v1" in client.datasets["smart-tutor-ask"].tags


def test_a_later_run_reads_the_tagged_version_without_pushing() -> None:
    client, dataset = FakeLangSmith(), _dataset(Q1, Q2)
    versioned_examples(client, dataset, dataset.splits["smoke"])
    again = versioned_examples(client, dataset, dataset.splits["smoke"])
    assert client.created == 1
    assert _pairs(again) == _pairs([Q1, Q2])


def test_an_edited_split_under_the_same_version_is_refused() -> None:
    client = FakeLangSmith()
    versioned_examples(client, _dataset(Q1, Q2), _dataset(Q1, Q2).splits["smoke"])
    edited = _dataset(Q1)
    with pytest.raises(DatasetError, match="new version"):
        versioned_examples(client, edited, edited.splits["smoke"])


def test_a_new_version_replaces_the_split_and_the_old_tag_keeps_its_examples() -> None:
    client = FakeLangSmith()
    versioned_examples(client, _dataset(Q1, Q2), _dataset(Q1, Q2).splits["smoke"])
    v2 = _dataset(Q2, version="smoke-v2")
    assert _pairs(versioned_examples(client, v2, v2.splits["smoke"])) == _pairs([Q2])
    old = client.list_examples(dataset_name="smart-tutor-ask", splits=["smoke"], as_of="smoke-v1")
    assert _pairs(list(old)) == _pairs([Q1, Q2])
