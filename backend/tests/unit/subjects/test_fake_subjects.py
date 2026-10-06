from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import GENERAL_SUBJECT_ID, Subject
from tests.fakes.subjects import InMemorySubjects

A = SubjectId("s-a")
B = SubjectId("s-b")


def test_insert_or_get_reuses_by_normalized_name() -> None:
    subjects = InMemorySubjects()
    first = subjects.insert_or_get(Subject(A, "Deep Learning"), "deep learning", [1.0, 0.0])
    again = subjects.insert_or_get(Subject(B, "DEEP  LEARNING"), "deep learning", [1.0, 0.0])
    assert again == first == Subject(A, "Deep Learning")
    assert subjects.find_by_normalized_names(["deep learning", "nope"]) == {"deep learning": first}
    assert subjects.find_by_normalized_names([]) == {}


def test_most_similar_orders_by_cosine_and_skips_rows_without_embedding() -> None:
    subjects = InMemorySubjects({A: "Near", B: "Far", GENERAL_SUBJECT_ID: "General"}, {A: [1.0, 0.1], B: [0.0, 1.0]})
    top = subjects.most_similar([1.0, 0.0], limit=5)
    assert [c.subject.subject_id for c in top] == [A, B]
    assert top[0].similarity > top[1].similarity
    assert [c.subject.subject_id for c in subjects.most_similar([1.0, 0.0], limit=1)] == [A]


def test_missing_name_embeddings_are_listed_and_set() -> None:
    subjects = InMemorySubjects()
    assert subjects.missing_name_embeddings(limit=10) == [Subject(GENERAL_SUBJECT_ID, "General")]
    subjects.set_name_embedding(GENERAL_SUBJECT_ID, [0.5, 0.5])
    assert subjects.missing_name_embeddings(limit=10) == []
