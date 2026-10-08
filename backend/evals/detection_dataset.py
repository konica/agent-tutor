"""The labeled subject-detection dataset: first questions with the subjects detection should bind (PRD §10.1).

A learner is a set of seed documents; their subjects are the union of the documents' subjects. A *clear* item has
one right subject set; an *ambiguous* item straddles several, so asking is the right behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from evals.seed_corpus.manifest import SeedDocument, load_manifest

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "subject_detection.yaml"

Kind = Literal["single", "multi", "ambiguous"]


@dataclass(frozen=True)
class DetectionItem:
    id: str
    kind: Kind
    smoke: bool
    learner_documents: tuple[str, ...]
    question: str
    expected_subjects: tuple[str, ...]
    source_chunks: tuple[str, ...]

    @property
    def clear(self) -> bool:
        return self.kind != "ambiguous"

    def inputs(self) -> dict[str, Any]:
        return {"question": self.question, "learner_documents": list(self.learner_documents)}

    def reference_outputs(self) -> dict[str, Any]:
        return {"expected_subjects": list(self.expected_subjects), "clear": self.clear}


def learner_subjects(item: DetectionItem, docs: Mapping[str, SeedDocument]) -> list[str]:
    return sorted({subject for doc_id in item.learner_documents for subject in docs[doc_id].subjects})


def _validate(item: DetectionItem, docs: Mapping[str, SeedDocument]) -> None:
    if item.kind not in ("single", "multi", "ambiguous"):
        raise ValueError(f"{item.id}: unknown kind {item.kind!r}")
    if not item.question.strip():
        raise ValueError(f"{item.id}: empty question")
    unknown = [d for d in item.learner_documents if d not in docs]
    if unknown:
        raise ValueError(f"{item.id}: unknown documents {unknown}")
    if not 1 <= len(item.expected_subjects) <= 3:
        raise ValueError(f"{item.id}: needs 1-3 expected subjects, got {len(item.expected_subjects)}")
    subjects = learner_subjects(item, docs)
    if len(subjects) < 2:
        raise ValueError(f"{item.id}: learner has fewer than 2 subjects, so detection is skipped")
    outside = [s for s in item.expected_subjects if s not in subjects]
    if outside:
        raise ValueError(f"{item.id}: expected subjects {outside} are not the learner's subjects")
    if item.kind == "ambiguous" and len(item.expected_subjects) < 2:
        raise ValueError(f"{item.id}: an ambiguous item needs at least 2 expected subjects")


def _parse(entry: Mapping[str, Any]) -> DetectionItem:
    return DetectionItem(
        id=entry["id"],
        kind=entry["kind"],
        smoke=bool(entry["smoke"]),
        learner_documents=tuple(entry["learner_documents"]),
        question=entry["question"],
        expected_subjects=tuple(entry["expected_subjects"]),
        source_chunks=tuple(entry["source_chunks"]),
    )


def load_items(
    split: Literal["smoke", "full"],
    path: Path = DATASET_PATH,
    docs: Mapping[str, SeedDocument] | None = None,
) -> list[DetectionItem]:
    known = docs if docs is not None else {d.id: d for d in load_manifest()}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = [_parse(entry) for entry in data.get("items") or []]
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise ValueError(f"duplicate item id: {item.id}")
        seen.add(item.id)
        _validate(item, known)
    return [i for i in items if i.smoke] if split == "smoke" else items


def dump_items(items: Sequence[DetectionItem], path: Path) -> None:
    entries = [
        {
            "id": i.id,
            "kind": i.kind,
            "smoke": i.smoke,
            "learner_documents": list(i.learner_documents),
            "question": i.question,
            "expected_subjects": list(i.expected_subjects),
            "source_chunks": list(i.source_chunks),
        }
        for i in items
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"items": entries}, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
