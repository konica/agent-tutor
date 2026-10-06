import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FakeQueue, FixedClock, InMemoryLibrary, fake_tools
from smart_tutor.knowledge.application import (
    DocumentNotFoundError,
    DocumentService,
    IngestionService,
    RetryLimitError,
    RetryService,
    UploadService,
    retried_content,
    retry_message,
)
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UserId

ADA = UserId("ada")
SCAN = b"%PDF-1.7 tiny"  # fake extractor: too little text → "No text layer"


def failed_upload(data: bytes = SCAN) -> tuple[InMemoryLibrary, FakeObjectStore, IngestionService, DocumentId]:
    """Ada's document, failed after its first attempt."""
    library, objects = InMemoryLibrary(), FakeObjectStore()
    started = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS).start_upload(ADA, "scan.pdf")
    objects.objects[started.fields["key"]] = data
    ingestion = IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS)
    ingestion.ingest_upload(started.fields["key"])
    assert library.state.documents[started.document_id].state.value == "failed"
    return library, objects, ingestion, started.document_id


def test_retry_returns_document_and_content_to_processing_and_queues_the_content() -> None:
    library, _, _, doc_id = failed_upload()
    queue = FakeQueue()
    RetryService(library.unit_of_work, queue, max_attempts=3).retry(ADA, doc_id)

    doc = library.state.documents[doc_id]
    content = library.state.contents[doc.content_id]  # type: ignore[index]
    assert (doc.state.value, doc.failure_reason) == ("processing", None)
    assert (content.state.value, content.attempts) == ("processing", 2)
    assert [retried_content(m.body) for m in queue.sent] == [content.content_id]
    [view] = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert (view.state, view.attempt, view.max_attempts, view.can_retry) == ("processing", 2, 3, False)


def test_the_queued_retry_reprocesses_the_stored_file() -> None:
    library, objects, ingestion, doc_id = failed_upload()
    queue = FakeQueue()
    RetryService(library.unit_of_work, queue, max_attempts=3).retry(ADA, doc_id)
    content_id = retried_content(queue.sent[0].body)
    assert content_id is not None
    ingestion.process_content(content_id)  # same bytes → fails again, attempt 2
    [view] = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert (view.state, view.attempt, view.can_retry) == ("failed", 2, True)


def test_after_three_failed_attempts_there_is_no_retry() -> None:
    library, _, ingestion, doc_id = failed_upload()
    retries = RetryService(library.unit_of_work, FakeQueue(), max_attempts=3)
    for _ in range(2):
        retries.retry(ADA, doc_id)
        ingestion.process_content(library.state.documents[doc_id].content_id)  # type: ignore[arg-type]
    [view] = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert (view.state, view.attempt, view.can_retry) == ("failed", 3, False)
    assert view.failure_reason == "This file could not be processed"
    with pytest.raises(RetryLimitError):
        retries.retry(ADA, doc_id)
    assert library.state.documents[doc_id].state.value == "failed"


def test_a_second_retry_while_processing_changes_nothing() -> None:
    library, _, _, doc_id = failed_upload()
    queue = FakeQueue()
    retries = RetryService(library.unit_of_work, queue, max_attempts=3)
    retries.retry(ADA, doc_id)
    retries.retry(ADA, doc_id)
    content = library.state.contents[library.state.documents[doc_id].content_id]  # type: ignore[index]
    assert content.attempts == 2 and len(queue.sent) == 1


def test_a_failed_document_without_content_is_left_alone() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    uploads = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS)
    ingestion = IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS)
    for name in ("a.pdf", "copy.pdf"):  # the second is a duplicate: failed with no content
        started = uploads.start_upload(ADA, name)
        objects.objects[started.fields["key"]] = SCAN
        ingestion.ingest_upload(started.fields["key"])
    duplicate = started.document_id
    queue = FakeQueue()
    RetryService(library.unit_of_work, queue, max_attempts=3).retry(ADA, duplicate)
    assert library.state.documents[duplicate].failure_reason == "Duplicate uploads aren't supported yet"
    assert queue.sent == []
    views = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert next(v for v in views if v.document_id == duplicate).can_retry is False


def test_another_learner_cannot_retry_and_learns_nothing() -> None:
    library, _, _, doc_id = failed_upload()
    queue = FakeQueue()
    retries = RetryService(library.unit_of_work, queue, max_attempts=3)
    with pytest.raises(DocumentNotFoundError):
        retries.retry(UserId("bob"), doc_id)
    with pytest.raises(DocumentNotFoundError):
        retries.retry(ADA, DocumentId("00000000-0000-4000-8000-00000000dead"))
    assert library.state.documents[doc_id].state.value == "failed" and queue.sent == []


def test_a_failed_send_commits_nothing() -> None:
    library, _, _, doc_id = failed_upload()
    with pytest.raises(RuntimeError):
        RetryService(library.unit_of_work, FakeQueue(fail_send=True), max_attempts=3).retry(ADA, doc_id)
    content = library.state.contents[library.state.documents[doc_id].content_id]  # type: ignore[index]
    assert (library.state.documents[doc_id].state.value, content.attempts) == ("failed", 1)


def test_retry_messages_round_trip_and_reject_anything_else() -> None:
    assert retried_content(retry_message(ContentId("c1"))) == "c1"
    for body in ("not json", "[]", '{"Records": []}', '{"retry_content_id": 5}', '{"retry_content_id": ""}'):
        assert retried_content(body) is None


def test_processing_waits_for_a_retry_commit_by_locking_the_content() -> None:
    library, _, ingestion, doc_id = failed_upload()
    RetryService(library.unit_of_work, FakeQueue(), max_attempts=3).retry(ADA, doc_id)
    library.locked_contents.clear()
    ingestion.process_content(library.state.documents[doc_id].content_id)  # type: ignore[arg-type]
    assert library.locked_contents  # the first read is get_for_update, so it waits for the API's commit
