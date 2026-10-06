import pytest

from fakes import InMemorySubjects, fake_embeddings
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID, InvalidSubjectNameError, SubjectCatalogService


def service(repo: InMemorySubjects) -> SubjectCatalogService:
    ids = iter(f"s{i}" for i in range(100))
    return SubjectCatalogService(repo, fake_embeddings(8), new_id=lambda: next(ids))


def test_a_new_name_creates_one_subject_with_its_embedding_and_is_reused_after() -> None:
    repo = InMemorySubjects()
    created = service(repo).get_or_create("  Machine   Translation ")
    assert repo.names[created] == "Machine Translation" and len(repo.embeddings[created]) == 8
    assert service(repo).get_or_create("machine translation") == created
    assert len(repo.names) == 2  # General + the new one


def test_an_existing_name_is_reused_without_embedding() -> None:
    repo = InMemorySubjects()
    assert service(repo).get_or_create("GENERAL") == GENERAL_SUBJECT_ID
    assert repo.embeddings == {}


def test_an_invalid_name_is_rejected() -> None:
    with pytest.raises(InvalidSubjectNameError):
        service(InMemorySubjects()).get_or_create("x" * 61)


def test_unknown_lists_ids_not_in_the_catalog() -> None:
    assert service(InMemorySubjects()).unknown([GENERAL_SUBJECT_ID, SubjectId("nope")]) == {SubjectId("nope")}


def test_embed_missing_names_backfills_the_seeded_general() -> None:
    repo = InMemorySubjects()
    assert service(repo).embed_missing_names() == 1
    assert len(repo.embeddings[GENERAL_SUBJECT_ID]) == 8 and service(repo).embed_missing_names() == 0
