"""US-2b type-ahead: the learner's subjects first (by their names), then shared ones (canonical names)."""

from fakes import InMemorySubjects
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application import CatalogMatch, SubjectNames, SubjectSearch, SuggestionOrigin
from smart_tutor.subjects.domain.search import rank_matches
from smart_tutor.subjects.domain.subject import Subject

RAG, IR, RL = SubjectId("s-rag"), SubjectId("s-ir"), SubjectId("s-rl")
ADA = UserId("ada")
YOURS, SHARED = SuggestionOrigin.YOURS, SuggestionOrigin.SHARED


def test_yours_come_first_then_shared_prefix_matches_first() -> None:
    matches = rank_matches(
        "retriev",
        yours={RAG: "Retrieval-Augmented Generation", RL: "Reinforcement Learning"},
        shared=[Subject(IR, "Information Retrieval")],
    )
    assert matches == [
        CatalogMatch(RAG, "Retrieval-Augmented Generation", YOURS),
        CatalogMatch(IR, "Information Retrieval", SHARED),
    ]


def test_your_matches_are_compared_after_normalization_and_ordered_prefix_first() -> None:
    yours = {RAG: "Retrieval-Augmented Generation", IR: "Dense  RETRIEVAL"}
    assert [m.subject_id for m in rank_matches("  RETRIEVAL ", yours=yours, shared=[])] == [RAG, IR]


def test_a_shared_subject_the_learner_has_is_shown_once_as_theirs() -> None:
    matches = rank_matches("rag", yours={RAG: "RAG"}, shared=[Subject(RAG, "RAG")])
    assert matches == [CatalogMatch(RAG, "RAG", YOURS)]


def test_results_are_limited() -> None:
    shared = [Subject(SubjectId(f"s{i}"), f"Topic {i}") for i in range(20)]
    assert len(rank_matches("topic", yours={}, shared=shared, limit=8)) == 8


def test_blank_query_finds_nothing_without_asking_the_catalog() -> None:
    class Exploding(InMemorySubjects):
        def search(self, normalized_query, exclude, limit):  # type: ignore[no-untyped-def]
            raise AssertionError("no query expected")

    assert SubjectSearch(Exploding(), SubjectNames(Exploding())).search(ADA, "   ", set()) == []


def test_search_uses_the_catalog_and_the_learners_subjects() -> None:
    catalog = InMemorySubjects({RAG: "Retrieval-Augmented Generation", IR: "Information Retrieval", RL: "RL"})
    found = SubjectSearch(catalog, SubjectNames(catalog)).search(ADA, "retriev", {RAG})
    assert found == [
        CatalogMatch(RAG, "Retrieval-Augmented Generation", YOURS),
        CatalogMatch(IR, "Information Retrieval", SHARED),
    ]
