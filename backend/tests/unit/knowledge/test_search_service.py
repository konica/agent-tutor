"""SearchService: chunks only from the caller's ready, non-archived documents in the requested subjects."""

import pytest

from fakes import InMemoryLibrary, fake_embeddings, ingest_ready
from smart_tutor.knowledge.application import InvalidSearchError, SearchService
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID


def service(library: InMemoryLibrary) -> SearchService:
    return SearchService(library.unit_of_work, fake_embeddings())


def test_returns_the_callers_matching_chunk_with_citation_fields() -> None:
    library = InMemoryLibrary()
    doc_id = ingest_ready(library, "ada", "Attention is all you need.")
    [hit] = service(library).search(UserId("ada"), "Attention is all you need.", [GENERAL_SUBJECT_ID], k=5)
    assert hit.document_id == doc_id and hit.page == 1 and hit.text == "Attention is all you need."
    assert hit.document_title.endswith(".pdf")
    assert hit.score == pytest.approx(1.0)


def test_never_returns_another_learners_chunks_even_for_the_same_text() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention is all you need.")
    assert service(library).search(UserId("bob"), "Attention is all you need.", [GENERAL_SUBJECT_ID]) == []


def test_other_subjects_and_archived_documents_are_excluded() -> None:
    library = InMemoryLibrary()
    doc_id = ingest_ready(library, "ada", "Attention is all you need.")
    other = SubjectId("00000000-0000-4000-8000-000000000099")
    assert service(library).search(UserId("ada"), "Attention", [other]) == []
    library.state.documents[doc_id].archived = True
    assert service(library).search(UserId("ada"), "Attention", [GENERAL_SUBJECT_ID]) == []


def test_best_first_and_at_most_k() -> None:
    library = InMemoryLibrary()
    for text in ("alpha beta", "gamma delta", "epsilon zeta"):
        ingest_ready(library, "ada", text)
    hits = service(library).search(UserId("ada"), "gamma delta", [GENERAL_SUBJECT_ID], k=2)
    assert len(hits) == 2 and hits[0].text == "gamma delta"
    assert hits[0].score >= hits[1].score


@pytest.mark.parametrize(
    ("query", "subjects", "k"),
    [
        ("  ", [GENERAL_SUBJECT_ID], 5),
        ("x" * 4001, [GENERAL_SUBJECT_ID], 5),
        ("q", [], 5),
        ("q", [SubjectId(f"00000000-0000-4000-8000-{i:012d}") for i in range(4)], 5),
        ("q", [GENERAL_SUBJECT_ID], 0),
        ("q", [GENERAL_SUBJECT_ID], 21),
    ],
)
def test_rejects_invalid_requests(query: str, subjects: list[SubjectId], k: int) -> None:
    with pytest.raises(InvalidSearchError):
        service(InMemoryLibrary()).search(UserId("ada"), query, subjects, k)


def test_rejects_a_subject_id_that_is_not_a_uuid() -> None:
    with pytest.raises(InvalidSearchError):
        service(InMemoryLibrary()).search(UserId("ada"), "q", [SubjectId("not-a-uuid")])
