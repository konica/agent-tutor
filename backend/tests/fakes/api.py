"""ApiServices built from fakes, for tests of the API's routes."""

from typing import Any

import httpx

from fakes.clock import FixedClock
from fakes.knowledge import FakeObjectStore, InMemoryLibrary
from fakes.models import fake_embeddings
from fakes.parameters import TEST_LIMITS
from fakes.subjects import InMemorySubjects
from fakes.tutoring import InMemoryThreads
from smart_tutor.apps.api.agent_client import AgentClient
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, SubjectChoiceService, UploadService
from smart_tutor.subjects.application import SubjectCatalogService, SubjectNames, SubjectSuggester
from smart_tutor.tutoring.application import ConversationService


def _agent_not_expected(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, text="no agent in this test")


def fake_agent(handler: Any = _agent_not_expected) -> AgentClient:
    """An AgentClient whose requests `handler(httpx.Request) -> httpx.Response` answers (no network)."""
    return AgentClient("http://agent.test", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def api_services(
    library: InMemoryLibrary | None = None,
    objects: FakeObjectStore | None = None,
    threads: InMemoryThreads | None = None,
    catalog: InMemorySubjects | None = None,
    clock: FixedClock | None = None,
    **overrides: Any,
) -> ApiServices:
    """Every ApiServices field built from fakes sharing `library`, `objects`, `threads`, `catalog`; `overrides`
    replace fields."""
    library = library or InMemoryLibrary()
    objects = objects or FakeObjectStore()
    threads = threads or InMemoryThreads()
    catalog = catalog or InMemorySubjects()
    clock = clock or FixedClock()
    documents = DocumentService(library.unit_of_work)
    fields: dict[str, Any] = {
        "uploads": UploadService(library.unit_of_work, objects, clock, TEST_LIMITS),
        "documents": documents,
        "subjects": SubjectNames(catalog),
        "subject_choice": SubjectChoiceService(
            library.unit_of_work,
            SubjectSuggester(catalog, SubjectNames(catalog)),
            SubjectCatalogService(catalog, fake_embeddings(8)),
        ),
        "conversations": ConversationService(threads, documents, clock),
        "agent": fake_agent(),
    }
    fields.update(overrides)
    return ApiServices(**fields)
