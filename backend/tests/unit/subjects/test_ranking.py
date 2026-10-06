from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject
from smart_tutor.subjects.domain.suggestions import Candidate, Suggestion, SuggestionOrigin, rank_suggestions

GENERAL = Subject(SubjectId("s-general"), "General")
NLP = Subject(SubjectId("s-nlp"), "Natural Language Processing")
DL = Subject(SubjectId("s-dl"), "Deep Learning")
LLM = Subject(SubjectId("s-llm"), "Large Language Models")
COOK = Subject(SubjectId("s-cook"), "Cooking")
PROPOSED = ["Deep Learning", "Machine Translation", "Attention Mechanisms"]


def rank(similar=(), proposed=(), existing=None, yours=None):  # type: ignore[no-untyped-def]
    return rank_suggestions(
        similar=list(similar),
        proposed_names=list(proposed),
        existing_by_name=existing or {},
        yours=yours or {},
        fallback=GENERAL,
    )


def test_matching_shared_subjects_come_first_by_similarity_and_new_names_fill_the_rest() -> None:
    got = rank(
        similar=[Candidate(DL, 0.70), Candidate(NLP, 0.75), Candidate(COOK, 0.52)],
        proposed=["Machine Translation", "Attention Mechanisms", "Transformers"],
    )
    assert got == [
        Suggestion("Natural Language Processing", SuggestionOrigin.SHARED, NLP.subject_id),
        Suggestion("Deep Learning", SuggestionOrigin.SHARED, DL.subject_id),
        Suggestion("Machine Translation", SuggestionOrigin.NEW),
    ]


def test_the_learners_subjects_are_boosted_above_the_threshold_and_named_their_way() -> None:
    got = rank(
        similar=[Candidate(NLP, 0.70), Candidate(LLM, 0.66)], proposed=["A", "B", "C"], yours={LLM.subject_id: "LLMs"}
    )
    assert got[0] == Suggestion("LLMs", SuggestionOrigin.YOURS, LLM.subject_id)  # 0.66 + 0.05 > 0.70
    assert got[1].subject_id == NLP.subject_id and got[2] == Suggestion("A", SuggestionOrigin.NEW)


def test_a_proposed_name_that_exists_is_that_subject_not_a_new_name() -> None:
    got = rank(proposed=PROPOSED, existing={"deep learning": DL})
    assert got == [
        Suggestion("Deep Learning", SuggestionOrigin.SHARED, DL.subject_id),
        Suggestion("Machine Translation", SuggestionOrigin.NEW),
        Suggestion("Attention Mechanisms", SuggestionOrigin.NEW),
    ]


def test_a_proposed_name_equal_to_a_learners_own_name_is_their_subject() -> None:
    got = rank(proposed=["LLMs", "X", "Y"], yours={LLM.subject_id: "LLMs"})
    assert got[0] == Suggestion("LLMs", SuggestionOrigin.YOURS, LLM.subject_id)


def test_always_three_when_enough_candidates_exist() -> None:
    similar = [Candidate(NLP, 0.9), Candidate(DL, 0.8), Candidate(LLM, 0.7), Candidate(COOK, 0.69)]
    assert len(rank(similar=similar, proposed=PROPOSED)) == 3
    assert [s.origin for s in rank(proposed=PROPOSED)] == [SuggestionOrigin.NEW] * 3


def test_without_a_description_the_learners_subjects_then_general_fill_in() -> None:
    assert rank(yours={NLP.subject_id: "NLP", DL.subject_id: "Deep learning"}) == [
        Suggestion("Deep learning", SuggestionOrigin.YOURS, DL.subject_id),
        Suggestion("NLP", SuggestionOrigin.YOURS, NLP.subject_id),
    ]
    assert rank() == [Suggestion("General", SuggestionOrigin.SHARED, GENERAL.subject_id)]


def test_no_subject_is_suggested_twice() -> None:
    got = rank(
        similar=[Candidate(DL, 0.8)], proposed=["deep  learning", "Deep Learning", "Z"], existing={"deep learning": DL}
    )
    assert [s.name for s in got] == ["Deep Learning", "Z"]
