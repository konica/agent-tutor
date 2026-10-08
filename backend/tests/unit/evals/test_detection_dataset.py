from pathlib import Path

import pytest

from evals.detection_dataset import DetectionItem, dump_items, learner_subjects, load_items
from evals.seed_corpus.manifest import SeedDocument


def doc(doc_id: str, *subjects: str) -> SeedDocument:
    return SeedDocument(doc_id, "arxiv", doc_id, "CC-BY-4.0", "0" * 64, subjects, doc_id)


DOCS = {
    "a": doc("a", "NLP"),
    "b": doc("b", "Vision", "RL"),
    "c": doc("c", "NLP"),
}


def item(**changes: object) -> DetectionItem:
    base: dict[str, object] = {
        "id": "single-001",
        "kind": "single",
        "smoke": True,
        "learner_documents": ("a", "b"),
        "question": "What is attention?",
        "expected_subjects": ("NLP",),
        "source_chunks": ("a:0",),
    }
    return DetectionItem(**{**base, **changes})  # type: ignore[arg-type]


def write(tmp_path: Path, *items: DetectionItem) -> Path:
    path = tmp_path / "d.yaml"
    dump_items(items, path)
    return path


def test_properties_and_learner_subjects() -> None:
    i = item(kind="ambiguous", expected_subjects=("NLP", "RL"))
    assert not i.clear
    assert item().clear
    assert i.inputs() == {"question": "What is attention?", "learner_documents": ["a", "b"]}
    assert i.reference_outputs() == {"expected_subjects": ["NLP", "RL"], "clear": False}
    assert learner_subjects(i, DOCS) == ["NLP", "RL", "Vision"]


def test_round_trip(tmp_path: Path) -> None:
    items = [item(), item(id="multi-001", kind="multi", smoke=False, expected_subjects=("NLP", "RL", "Vision"))]
    assert load_items("full", write(tmp_path, *items), DOCS) == items


def test_smoke_split_returns_only_smoke_items(tmp_path: Path) -> None:
    path = write(tmp_path, item(), item(id="single-002", smoke=False))
    assert [i.id for i in load_items("smoke", path, DOCS)] == ["single-001"]
    assert [i.id for i in load_items("full", path, DOCS)] == ["single-001", "single-002"]


@pytest.mark.parametrize(
    "bad",
    [
        item(learner_documents=("a", "zzz")),
        item(expected_subjects=()),
        item(expected_subjects=("NLP", "RL", "Vision", "Other")),
        item(expected_subjects=("Chemistry",)),
        item(learner_documents=("a", "c")),  # one subject only
        item(kind="ambiguous", expected_subjects=("NLP",)),
    ],
)
def test_rejects_invalid_items(tmp_path: Path, bad: DetectionItem) -> None:
    with pytest.raises(ValueError):
        load_items("full", write(tmp_path, bad), DOCS)


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        load_items("full", write(tmp_path, item(), item()), DOCS)
