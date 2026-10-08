from evals.corpus_index import CorpusIndex, build_index
from evals.seed_corpus.manifest import SeedDocument
from evals.targets import detection_target
from fakes import FakePdfExtractor, PageChunker, fake_embeddings
from smart_tutor.tutoring.domain.detection import DetectionPolicy

PAGES = {"a": ["alpha page one"], "b": ["beta only page"]}
SUBJECTS = {"a": ("Math",), "b": ("Physics",)}


def doc(doc_id: str) -> SeedDocument:
    return SeedDocument(
        id=doc_id,
        source_type="arxiv",
        source_ref=doc_id,
        license="CC BY 4.0",
        sha256=doc_id * 4,
        subjects=SUBJECTS[doc_id],
        title=f"Doc {doc_id}",
    )


def index() -> CorpusIndex:
    return build_index(
        [doc("a"), doc("b")],
        lambda d: ("%PDF-1.4 " + "\f".join(PAGES[d.id])).encode(),
        FakePdfExtractor(),
        PageChunker(),
        fake_embeddings(),
    )


INPUTS = {"question": "alpha page one", "learner_documents": ["a", "b"]}


def test_returns_subject_names_and_scores_keyed_by_name() -> None:
    target = detection_target(index(), fake_embeddings(), DetectionPolicy(0.0, 0.0, 0.0))
    out = target(INPUTS)
    assert out["unsure"] is False
    assert "Math" in out["subjects"]
    assert set(out["scores"]) <= {"Math", "Physics"}
    assert out["scores"]["Math"] > 0.99


def test_too_high_threshold_is_unsure_but_still_names_a_subject() -> None:
    target = detection_target(index(), fake_embeddings(), DetectionPolicy(1.1, 0.0, 0.0))
    out = target(INPUTS)
    assert out["unsure"] is True
    assert out["subjects"] == ["Math"]
