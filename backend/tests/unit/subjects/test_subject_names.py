from fakes import InMemorySubjects
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID, SubjectNames


def test_resolves_canonical_names_and_skips_unknown_ids() -> None:
    names = SubjectNames(InMemorySubjects())
    unknown = SubjectId("00000000-0000-4000-8000-0000000000ff")
    assert names.names_for(UserId("ada"), [GENERAL_SUBJECT_ID, unknown]) == {GENERAL_SUBJECT_ID: "General"}


def test_no_ids_no_names() -> None:
    assert SubjectNames(InMemorySubjects()).names_for(UserId("ada"), []) == {}
