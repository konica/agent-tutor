"""GET /me/subjects: the subjects of the caller's ready documents, by name."""

from fastapi.testclient import TestClient

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FakeTokenVerifier,
    FixedClock,
    InMemoryLibrary,
    InMemorySubjects,
    api_services,
    ingest_ready,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID

AUTH = {"Authorization": "Bearer t-ada"}
RL = SubjectId("00000000-0000-4000-8000-0000000000a1")
AG = SubjectId("00000000-0000-4000-8000-0000000000a2")
UNKNOWN = SubjectId("00000000-0000-4000-8000-0000000000ff")


def make_client(library: InMemoryLibrary, catalog: InMemorySubjects | None = None) -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    services = api_services(library, catalog=catalog)
    return TestClient(create_app(Settings(), verifier=verifier, services=services))


def test_lists_the_subjects_of_ready_documents_by_name() -> None:
    catalog = InMemorySubjects({GENERAL_SUBJECT_ID: "General", RL: "Reinforcement Learning", AG: "AI Agents"})
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Policies act.", subject_ids=[RL, AG])
    ingest_ready(library, "ada", "Agents plan.", subject_ids=[AG])
    client = make_client(library, catalog)

    response = client.get("/me/subjects", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == [
        {"subject_id": AG, "name": "AI Agents"},
        {"subject_id": RL, "name": "Reinforcement Learning"},
    ]


def test_no_ready_documents_is_an_empty_list() -> None:
    library = InMemoryLibrary()  # an upload still processing has no subjects
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId("ada"), "a.pdf"
    )

    assert make_client(library).get("/me/subjects", headers=AUTH).json() == []


def test_a_subject_without_a_name_shows_a_placeholder() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "x", subject_ids=[UNKNOWN])  # the catalog lacks UNKNOWN

    assert make_client(library).get("/me/subjects", headers=AUTH).json() == [
        {"subject_id": UNKNOWN, "name": "Unnamed subject"}
    ]


def test_requires_a_token() -> None:
    assert make_client(InMemoryLibrary()).get("/me/subjects").status_code == 401
