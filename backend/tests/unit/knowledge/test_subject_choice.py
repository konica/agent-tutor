"""US-2b: a learner chooses 1-3 subjects for a processed document from its suggestions (PRD §9.2 step 5, D20)."""

import pytest
from langchain_core.messages import AIMessage

from fakes import (
    DESCRIPTION_ARGS,
    TEST_LIMITS,
    FakeObjectStore,
    FixedClock,
    InMemoryLibrary,
    InMemorySubjects,
    describing_chat_model,
    fake_embeddings,
    fake_tools,
)
from smart_tutor.knowledge.application import (
    ArchiveService,
    DocumentNotFoundError,
    DocumentService,
    DocumentStateError,
    IngestionService,
    InvalidSubjectsError,
    SubjectChoiceService,
    UploadService,
)
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId
from smart_tutor.subjects.application import (
    GENERAL_SUBJECT_ID,
    SubjectCatalogService,
    SubjectNames,
    SubjectSearch,
    SubjectSuggester,
    SuggestionOrigin,
)

ADA, BOB = UserId("ada"), UserId("bob")
SENTENCE = "A sentence about attention mechanisms. " * 5
UNKNOWN = SubjectId("00000000-0000-4000-8000-0000000000ff")


def pdf(text: str) -> bytes:
    return b"%PDF-1.7 " + text.encode()


class World:
    def __init__(self, chat: AIMessage | None = None) -> None:
        self.library, self.objects = InMemoryLibrary(), FakeObjectStore()
        self.subjects = InMemorySubjects()
        self.uploads = UploadService(self.library.unit_of_work, self.objects, FixedClock(), TEST_LIMITS)
        self.ingestion = IngestionService(
            self.library.unit_of_work, self.objects, fake_tools(chat=describing_chat_model(chat)), TEST_LIMITS
        )
        self.catalog = SubjectCatalogService(self.subjects, fake_embeddings(8))
        suggester = SubjectSuggester(self.subjects, SubjectNames(self.subjects))
        search = SubjectSearch(self.subjects, SubjectNames(self.subjects))
        self.choice = SubjectChoiceService(
            self.library.unit_of_work, suggester, self.catalog, search=search, max_attempts=3
        )
        self.documents = DocumentService(self.library.unit_of_work, max_attempts=3)

    def upload(self, user_id: UserId = ADA, text: str = SENTENCE, *, ingest: bool = True) -> DocumentId:
        started = self.uploads.start_upload(user_id, "paper.pdf")
        if ingest:
            self.objects.objects[started.fields["key"]] = pdf(text)
            self.ingestion.ingest_upload(started.fields["key"])
        return DocumentId(started.document_id)

    def state(self, user_id: UserId = ADA) -> list[tuple[str, tuple[SubjectId, ...]]]:
        return [(d.state, d.subject_ids) for d in self.documents.list_documents(user_id)]


def test_suggestions_offer_three_new_names_on_an_empty_catalog() -> None:
    w = World()
    document_id = w.upload()

    offered = w.choice.suggestions(ADA, document_id)

    assert offered.document_id == document_id
    assert offered.title == DESCRIPTION_ARGS["title"]
    assert offered.summary == DESCRIPTION_ARGS["summary"]
    assert [(s.name, s.origin, s.subject_id) for s in offered.suggestions] == [
        (name, SuggestionOrigin.NEW, None) for name in DESCRIPTION_ARGS["proposed_subject_names"]
    ]


def test_choosing_a_new_name_creates_the_subject_and_makes_the_document_ready() -> None:
    w = World()
    ada_doc = w.upload(ADA)
    bob_doc = w.upload(BOB, SENTENCE + " different bytes")

    view = w.choice.choose(ADA, ada_doc, [], ["Machine Translation"])

    assert view.state == "ready"
    [subject_id] = view.subject_ids
    assert w.subjects.canonical_names([subject_id]) == {subject_id: "Machine Translation"}
    assert w.state() == [("ready", (subject_id,))]
    again = w.choice.choose(BOB, bob_doc, [], ["machine translation"])
    assert again.subject_ids == (subject_id,)


def test_choosing_an_existing_subject_by_id() -> None:
    w = World()
    document_id = w.upload()

    view = w.choice.choose(ADA, document_id, [GENERAL_SUBJECT_ID], [])

    assert (view.state, view.subject_ids) == ("ready", (GENERAL_SUBJECT_ID,))


def test_unknown_ids_are_rejected_and_nothing_changes() -> None:
    w = World()
    document_id = w.upload()

    with pytest.raises(InvalidSubjectsError):
        w.choice.choose(ADA, document_id, [UNKNOWN], [])

    assert w.state() == [("awaiting_subjects", ())]


def test_a_typed_name_creates_a_shared_subject() -> None:
    world = World()
    doc = world.upload()
    world.choice.choose(ADA, doc, [], ["  Tool   Use  "])
    [(state, (sid,))] = world.state()
    assert state == "ready" and world.subjects.names[sid] == "Tool Use"


def test_a_typed_name_equal_to_an_existing_subject_after_normalization_reuses_it() -> None:
    world = World()
    existing = world.catalog.get_or_create("Information Retrieval")
    doc = world.upload()
    world.choice.choose(ADA, doc, [], ["ＩＮＦＯＲＭＡＴＩＯＮ  retrieval "])  # NFKC full-width, case, spaces
    assert world.state() == [("ready", (existing,))]


def test_a_typed_name_over_60_characters_is_rejected_and_nothing_changes() -> None:
    world = World()
    doc = world.upload()
    with pytest.raises(InvalidSubjectsError, match="60"):
        world.choice.choose(ADA, doc, [], ["x" * 61])
    assert world.state() == [("awaiting_subjects", ())]


def test_search_puts_the_learners_subjects_first() -> None:
    world = World()
    mine = world.catalog.get_or_create("Retrieval-Augmented Generation")
    shared = world.catalog.get_or_create("Information Retrieval")
    doc = world.upload()
    world.choice.choose(ADA, doc, [mine], [])
    assert [(m.subject_id, m.origin) for m in world.choice.search(ADA, "retriev")] == [
        (mine, SuggestionOrigin.YOURS),
        (shared, SuggestionOrigin.SHARED),
    ]
    assert [m.origin for m in world.choice.search(BOB, "retriev")] == [SuggestionOrigin.SHARED] * 2


@pytest.mark.parametrize(
    ("ids", "names"),
    [
        ([], []),
        ([GENERAL_SUBJECT_ID, SubjectId("a"), SubjectId("b"), SubjectId("c")], []),
        ([GENERAL_SUBJECT_ID, GENERAL_SUBJECT_ID], []),
        ([], ["Deep Learning", "Deep Learning"]),
    ],
)
def test_zero_more_than_three_or_duplicates_are_rejected(ids: list[SubjectId], names: list[str]) -> None:
    w = World()
    document_id = w.upload()
    before = dict(w.subjects.names)

    with pytest.raises(InvalidSubjectsError):
        w.choice.choose(ADA, document_id, ids, names)

    assert w.subjects.names == before
    assert w.state() == [("awaiting_subjects", ())]


def test_a_new_name_resolving_to_a_chosen_subject_is_a_duplicate() -> None:
    w = World()
    document_id = w.upload()
    deep_learning = w.catalog.get_or_create("Deep Learning")

    with pytest.raises(InvalidSubjectsError):
        w.choice.choose(ADA, document_id, [deep_learning], ["Deep Learning"])

    assert w.state() == [("awaiting_subjects", ())]


def test_another_learners_document_is_not_found() -> None:
    w = World()
    document_id = w.upload(ADA)

    with pytest.raises(DocumentNotFoundError):
        w.choice.suggestions(BOB, document_id)
    with pytest.raises(DocumentNotFoundError):
        w.choice.choose(BOB, document_id, [GENERAL_SUBJECT_ID], [])

    assert w.state() == [("awaiting_subjects", ())]


def test_a_processing_document_has_no_suggestions_and_takes_no_subjects() -> None:
    w = World()
    document_id = w.upload(ingest=False)

    with pytest.raises(DocumentStateError):
        w.choice.suggestions(ADA, document_id)
    with pytest.raises(DocumentStateError):
        w.choice.choose(ADA, document_id, [GENERAL_SUBJECT_ID], [])

    assert w.state() == [("processing", ())]


def test_without_a_description_the_picker_still_has_a_suggestion() -> None:
    w = World(chat=AIMessage(content="It's a paper about attention."))
    document_id = w.upload()

    offered = w.choice.suggestions(ADA, document_id)

    assert offered.summary is None
    assert [(s.name, s.origin, s.subject_id) for s in offered.suggestions] == [
        ("General", SuggestionOrigin.SHARED, GENERAL_SUBJECT_ID)
    ]


def test_an_archived_document_cant_get_suggestions_or_subjects_until_restored() -> None:
    w = World()
    document_id = w.upload()
    ArchiveService(w.library.unit_of_work, FixedClock(), max_attempts=3).archive(ADA, document_id)

    with pytest.raises(DocumentStateError, match="Restore"):
        w.choice.suggestions(ADA, document_id)
    with pytest.raises(DocumentStateError, match="Restore"):
        w.choice.choose(ADA, document_id, [GENERAL_SUBJECT_ID], [])

    assert w.state() == []  # the active tab shows nothing; the document keeps no subjects
    [archived] = w.documents.list_documents(ADA, archived=True)
    assert (archived.state, archived.subject_ids) == ("awaiting_subjects", ())


def test_a_ready_documents_subjects_change_and_the_library_and_my_subjects_follow() -> None:
    w = World()
    document_id = w.upload()
    w.choice.choose(ADA, document_id, [GENERAL_SUBJECT_ID], [])

    view = w.choice.choose(ADA, document_id, [], ["Machine Translation", "Tool Use"])

    assert view.state == "ready"  # no state change, so nothing is processed again
    assert GENERAL_SUBJECT_ID not in view.subject_ids and len(view.subject_ids) == 2
    assert w.state() == [("ready", view.subject_ids)]
    with w.library.unit_of_work() as tx:
        assert tx.documents.subject_ids_readable_by(ADA) == set(view.subject_ids)  # My subjects
    assert w.documents.list_documents(ADA, subject_ids=[GENERAL_SUBJECT_ID]) == []
    assert [d.document_id for d in w.documents.list_documents(ADA, subject_ids=view.subject_ids[:1])] == [document_id]


@pytest.mark.parametrize(("ids", "names"), [([], []), ([GENERAL_SUBJECT_ID], ["A", "B", "C"])])
def test_a_ready_document_keeps_its_subjects_when_zero_or_more_than_three_are_chosen(
    ids: list[SubjectId], names: list[str]
) -> None:
    w = World()
    document_id = w.upload()
    w.choice.choose(ADA, document_id, [GENERAL_SUBJECT_ID], [])

    with pytest.raises(InvalidSubjectsError):
        w.choice.choose(ADA, document_id, ids, names)

    assert w.state() == [("ready", (GENERAL_SUBJECT_ID,))]


def test_an_archived_ready_documents_subjects_cant_change_until_restored() -> None:
    w = World()
    document_id = w.upload()
    w.choice.choose(ADA, document_id, [GENERAL_SUBJECT_ID], [])
    archive = ArchiveService(w.library.unit_of_work, FixedClock(), max_attempts=3)
    archive.archive(ADA, document_id)

    with pytest.raises(DocumentStateError, match="Restore"):
        w.choice.choose(ADA, document_id, [], ["Tool Use"])
    [archived] = w.documents.list_documents(ADA, archived=True)
    assert archived.subject_ids == (GENERAL_SUBJECT_ID,)

    archive.restore(ADA, document_id)
    view = w.choice.choose(ADA, document_id, [], ["Tool Use"])
    assert view.state == "ready" and GENERAL_SUBJECT_ID not in view.subject_ids
