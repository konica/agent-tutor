from pathlib import Path

import numpy as np

from evals.corpus_index import (
    CorpusIndex,
    SeedCorpusRetriever,
    build_index,
    index_key,
    load_or_build_index,
    subject_id,
)
from evals.seed_corpus.manifest import SeedDocument
from fakes import FakePdfExtractor, PageChunker, fake_embeddings
from smart_tutor.tutoring.domain.detection import best_scores

PAGES = {
    "a": ["alpha page one", "alpha page two"],
    "b": ["beta only page"],
    "c": ["gamma page one"],
}
SUBJECTS = {"a": ("Math", "Physics"), "b": ("Physics",), "c": ("Biology",)}


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


def read_pdf(d: SeedDocument) -> bytes:
    return ("%PDF-1.4 " + "\f".join(PAGES[d.id])).encode()


def build() -> CorpusIndex:
    return build_index([doc(i) for i in "abc"], read_pdf, FakePdfExtractor(), PageChunker(), fake_embeddings())


def retriever(library: list[str]) -> SeedCorpusRetriever:
    return SeedCorpusRetriever(build(), library, fake_embeddings())


def test_chunks_have_one_based_pages_and_stable_ids() -> None:
    index = build()
    of_a = [(c.chunk_id, c.document_id, c.page, c.text) for c in index.chunks if c.document_id == "a"]
    assert of_a == [("a:0", "a", 1, "alpha page one"), ("a:1", "a", 2, "alpha page two")]
    assert [c.chunk_id for c in build().chunks] == [c.chunk_id for c in index.chunks]


def test_vectors_are_unit_norm_and_aligned() -> None:
    index = build()
    assert index.vectors.shape[0] == len(index.chunks) == 4
    assert np.allclose(np.linalg.norm(index.vectors, axis=1), 1.0)


async def test_search_never_returns_documents_without_the_subject() -> None:
    hits = await retriever(["a", "b", "c"]).search("alpha page one", [subject_id("Biology")], k=10)
    assert {h.chunk_id for h in hits} == {"c:0"}


async def test_hit_subject_ids_exclude_unrequested_subjects() -> None:
    hits = await retriever(["a"]).search("alpha page one", [subject_id("Physics")], k=10)
    assert hits
    assert all(h.subject_ids == (subject_id("Physics"),) for h in hits)


async def test_exact_text_scores_one_and_ranks_first() -> None:
    hits = await retriever(["a", "b"]).search("beta only page", [subject_id("Math"), subject_id("Physics")], k=3)
    assert hits[0].chunk_id == "b:0"
    assert abs(hits[0].score - 1.0) < 1e-6
    assert hits[0].document_title == "Doc b"
    assert hits[0].page == 1
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


async def test_documents_outside_library_are_never_returned() -> None:
    hits = await retriever(["a"]).search("beta only page", [subject_id("Physics")], k=10)
    assert {h.chunk_id for h in hits} == {"a:0", "a:1"}


async def test_subject_without_library_document_has_no_score() -> None:
    wanted = [subject_id("Physics"), subject_id("Biology")]
    hits = await retriever(["a", "b"]).search("alpha page one", wanted, k=10)
    scores = best_scores(hits, wanted)
    assert subject_id("Physics") in scores
    assert subject_id("Biology") not in scores


async def test_k_limits_results() -> None:
    hits = await retriever(["a", "b"]).search("alpha", [subject_id("Physics")], k=2)
    assert len(hits) == 2


def test_index_key_changes_with_any_input() -> None:
    docs = [doc("a"), doc("b")]
    base = index_key("chunker", "model", docs)
    assert index_key("chunker", "model", docs) == base
    assert index_key("other", "model", docs) != base
    assert index_key("chunker", "other", docs) != base
    assert index_key("chunker", "model", docs[:1]) != base


def test_load_or_build_index_builds_once_then_reads_cache(tmp_path: Path) -> None:
    calls: list[int] = []

    def counting_build() -> CorpusIndex:
        calls.append(1)
        return build()

    docs = [doc(i) for i in "abc"]
    first = load_or_build_index(docs, tmp_path, "k1", counting_build)
    second = load_or_build_index(docs, tmp_path, "k1", counting_build)
    assert calls == [1]
    assert second.chunks == first.chunks
    assert np.allclose(second.vectors, first.vectors)
    assert second.documents == first.documents
