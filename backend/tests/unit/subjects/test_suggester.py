from fakes import InMemorySubjects, fake_embeddings
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application import (
    GENERAL_SUBJECT_ID,
    SubjectNames,
    SubjectSuggester,
    Suggestion,
    SuggestionOrigin,
)


def test_suggest_uses_similarity_the_learners_subjects_and_new_names() -> None:
    emb = fake_embeddings(8)
    nlp, cook = SubjectId("s-nlp"), SubjectId("s-cook")
    repo = InMemorySubjects(
        {GENERAL_SUBJECT_ID: "General", nlp: "NLP", cook: "Cooking"},
        {nlp: emb.embed_query("NLP"), cook: emb.embed_query("Cooking")},
    )
    suggester = SubjectSuggester(repo, SubjectNames(repo))
    got = suggester.suggest(UserId("ada"), emb.embed_query("NLP"), ["Cooking", "Machine Translation", "Attention"], [])
    # NLP (similarity 1.0) and Cooking (proposed name equals it, 1.0) tie, so their order is by name.
    assert {got[0].subject_id, got[1].subject_id} == {nlp, cook}
    assert got[2] == Suggestion("Machine Translation", SuggestionOrigin.NEW)


def test_suggest_without_a_summary_offers_the_learners_subjects() -> None:
    repo = InMemorySubjects()
    got = SubjectSuggester(repo, SubjectNames(repo)).suggest(UserId("ada"), None, [], [GENERAL_SUBJECT_ID])
    assert got == [Suggestion("General", SuggestionOrigin.YOURS, GENERAL_SUBJECT_ID)]
