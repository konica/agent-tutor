"""SearchService: chunks only from the caller's ready, non-archived documents, in any subject."""

import uuid

import pytest

from fakes import InMemoryLibrary, fake_embeddings, ingest_ready
from smart_tutor.knowledge.application import InvalidSearchError, SearchService
from smart_tutor.shared.domain.ids import SubjectId, UserId


def service(library: InMemoryLibrary) -> SearchService:
    return SearchService(library.unit_of_work, fake_embeddings())


def test_returns_the_callers_matching_chunk_with_citation_fields() -> None:
    library = InMemoryLibrary()
    doc_id = ingest_ready(library, "ada", "Attention is all you need.")
    [hit] = service(library).search(UserId("ada"), "Attention is all you need.", k=5)
    assert hit.document_id == doc_id and hit.page == 1 and hit.text == "Attention is all you need."
    assert hit.document_title.endswith(".pdf")
    assert hit.score == pytest.approx(1.0)


def test_a_hit_carries_the_display_title_content_title_then_override() -> None:
    library = InMemoryLibrary()
    doc_id = ingest_ready(library, "ada", "Attention is all you need.")
    document = library.state.documents[doc_id]
    assert document.content_id is not None
    library.state.contents[document.content_id].title = "Attention Is All You Need"

    def title() -> str:
        [hit] = service(library).search(UserId("ada"), "Attention is all you need.")
        return hit.document_title

    assert title() == "Attention Is All You Need"
    document.title_override = "My notes"
    assert title() == "My notes"


def test_never_returns_another_learners_chunks_even_for_the_same_text() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention is all you need.")
    assert service(library).search(UserId("bob"), "Attention is all you need.") == []


def test_archived_documents_are_excluded_and_documents_in_any_subject_are_included() -> None:
    library = InMemoryLibrary()
    other = SubjectId("00000000-0000-4000-8000-000000000099")
    archived = ingest_ready(library, "ada", "Attention is all you need.")
    ingest_ready(library, "ada", "Attention scales with heads.", subject_ids=[other])
    library.state.documents[archived].archived = True
    hits = service(library).search(UserId("ada"), "Attention")
    assert [h.text for h in hits] == ["Attention scales with heads."]


def test_best_first_and_at_most_k() -> None:
    library = InMemoryLibrary()
    for text in ("alpha beta", "gamma delta", "epsilon zeta"):
        ingest_ready(library, "ada", text)
    hits = service(library).search(UserId("ada"), "gamma delta", k=2)
    assert len(hits) == 2 and hits[0].text == "gamma delta"
    assert hits[0].score >= hits[1].score


@pytest.mark.parametrize(("query", "k"), [("  ", 5), ("x" * 4001, 5), ("q", 0), ("q", 21)])
def test_rejects_invalid_requests(query: str, k: int) -> None:
    with pytest.raises(InvalidSearchError):
        service(InMemoryLibrary()).search(UserId("ada"), query, k)


def test_document_ids_limit_the_search_to_those_documents() -> None:
    library = InMemoryLibrary()
    first = ingest_ready(library, "ada", "Attention weighs tokens.")
    ingest_ready(library, "ada", "Photosynthesis makes glucose.")
    hits = service(library).search(UserId("ada"), "Photosynthesis makes glucose.", 5, document_ids=[str(first)])
    assert hits and {h.document_id for h in hits} == {first}


def test_an_empty_list_finds_nothing_and_malformed_ids_are_ignored() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    assert service(library).search(UserId("ada"), "Attention", 5, document_ids=[]) == []
    assert service(library).search(UserId("ada"), "Attention", 5, document_ids=["not-a-uuid"]) == []


def test_too_many_document_ids_is_invalid() -> None:
    with pytest.raises(InvalidSearchError):
        service(InMemoryLibrary()).search(UserId("ada"), "q", 5, document_ids=[str(uuid.uuid4()) for _ in range(201)])
