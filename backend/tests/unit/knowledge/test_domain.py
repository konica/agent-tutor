from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from smart_tutor.knowledge.domain.chunk import MAX_CHUNK_CHARS, validate_chunk
from smart_tutor.knowledge.domain.content import (
    NO_TEXT_LAYER,
    UNREADABLE_PDF,
    Content,
    ContentState,
    content_key,
    has_text_layer,
    pages_key,
    too_many_pages,
)
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD, Document, DocumentFilter, DocumentState
from smart_tutor.knowledge.domain.errors import (
    ContentStateError,
    DocumentStateError,
    InvalidChunkError,
    InvalidFileNameError,
    InvalidSubjectsError,
    RetryLimitError,
)
from smart_tutor.knowledge.domain.upload import Upload, parse_upload_key, upload_key
from smart_tutor.shared.domain.ids import ContentId, DocumentId, SubjectId, UploadId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID

NOW = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
SHA = "a" * 64


def new_document(file_name: str = "lewis-rag-2020.pdf") -> Document:
    return Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), file_name, NOW)


def test_a_started_upload_is_processing_and_titled_by_its_file_name() -> None:
    doc = new_document()
    assert doc.state is DocumentState.PROCESSING
    assert doc.title == "lewis-rag-2020.pdf"
    assert doc.content_id is None
    assert doc.awaiting_upload


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("C:\\Users\\ada\\paper.pdf", "paper.pdf"),
        ("/home/ada/paper.pdf", "paper.pdf"),
        ("  paper.pdf  ", "paper.pdf"),
        ("pa\x00per\n.pdf", "paper.pdf"),
        ("pa\x85per\u202e.\u200fpdf", "paper.pdf"),
        ("x" * 300 + ".pdf", "x" * 255),
    ],
)
def test_file_name_is_cleaned(raw: str, clean: str) -> None:
    assert new_document(raw).file_name == clean


@pytest.mark.parametrize("raw", ["", "   ", "C:\\folder\\", "\x00\x01"])
def test_blank_file_name_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidFileNameError):
        new_document(raw)


def test_linking_content_keeps_the_document_processing() -> None:
    doc = new_document()
    doc.link_content(ContentId("c1"))
    assert doc.content_id == "c1"
    assert doc.state is DocumentState.PROCESSING
    assert not doc.awaiting_upload


def test_a_document_links_content_only_once() -> None:
    doc = new_document()
    doc.link_content(ContentId("c1"))
    with pytest.raises(DocumentStateError):
        doc.link_content(ContentId("c2"))


def test_failing_records_the_reason() -> None:
    doc = new_document()
    doc.fail(DUPLICATE_UPLOAD)
    assert doc.state is DocumentState.FAILED
    assert doc.failure_reason == "Duplicate uploads aren't supported yet"
    assert not doc.awaiting_upload
    with pytest.raises(DocumentStateError):
        doc.fail("again")


def test_only_the_owner_can_read_a_document() -> None:
    doc = new_document()
    assert doc.can_be_read_by(UserId("ada"))
    assert not doc.can_be_read_by(UserId("bob"))


def test_searchable_only_by_its_owner_when_ready_and_unarchived() -> None:
    doc = linked_document()
    doc.await_subjects()
    doc.choose_subjects([GENERAL_SUBJECT_ID])
    assert doc.searchable_by(UserId("ada"))
    assert not doc.searchable_by(UserId("bob"))
    doc.archived = True
    assert not doc.searchable_by(UserId("ada"))


def test_a_processing_document_is_not_searchable() -> None:
    assert not new_document().searchable_by(UserId("ada"))


def test_title_override_wins() -> None:
    doc = new_document()
    doc.title_override = "RAG for knowledge-intensive NLP"
    assert doc.title == "RAG for knowledge-intensive NLP"


def test_first_upload_creates_processing_content_at_its_hash_key() -> None:
    content = Content.first_upload(ContentId("c1"), SHA, 1234, UserId("ada"))
    assert content.state is ContentState.PROCESSING
    assert content.s3_key == content_key(SHA) == f"contents/{SHA}.pdf"
    assert content.attempts == 1
    assert content.processed_by_user_id == "ada"


@pytest.mark.parametrize("bad", ["A" * 64, "a" * 63, "g" * 64, ""])
def test_content_needs_a_lowercase_sha256(bad: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        Content.first_upload(ContentId("c1"), bad, 1, UserId("ada"))


def test_upload_key_round_trips() -> None:
    uid = "b5f3c1a2-0d4e-4f6a-9b7c-1e2d3c4b5a69"
    upload = Upload(UploadId(uid), UserId("ada"), NOW)
    assert upload.key == upload_key(UserId("ada"), UploadId(uid)) == f"uploads/ada/{uid}.pdf"
    assert parse_upload_key(f"uploads/ada/{uid}.pdf") == ("ada", uid)
    assert parse_upload_key(f"uploads/ada/{uid.upper()}.pdf") == ("ada", uid.upper())


@pytest.mark.parametrize(
    "key",
    [
        "contents/x.pdf",
        "uploads/ada.pdf",
        "uploads/ada/u1.txt",
        "uploads/ada/nope.pdf",
        "uploads/ada/b5f3c1a2-0d4e-4f6a-9b7c-1e2d3c4b5a6.pdf",
        "uploads/a/b/c.pdf",
        "uploads//u1.pdf",
    ],
)
def test_other_keys_are_not_upload_keys(key: str) -> None:
    assert parse_upload_key(key) is None


def test_pages_key_and_failure_reasons() -> None:
    assert pages_key(SHA) == f"contents/{SHA}.pages.json"
    assert UNREADABLE_PDF == "This file isn't a readable PDF"
    assert NO_TEXT_LAYER == "No text layer (scanned PDFs are not supported yet)"
    assert GENERAL_SUBJECT_ID == "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        (["x" * 49], False),
        (["x" * 60, ""], False),
        (["x" * 100], True),
        (["x" * 50], True),
        ([], False),
        ([" \n\t" * 100], False),
        (["x " * 50], True),
    ],
)
def test_has_text_layer(pages: list[str], expected: bool) -> None:
    assert has_text_layer(pages) is expected


def processing_content() -> Content:
    return Content.first_upload(ContentId("c1"), SHA, 10, UserId("ada"))


def test_content_ready_records_how_it_was_processed() -> None:
    content = processing_content()
    content.ready(pages=3, text_key=pages_key(SHA), chunker="c:v1", embedding_model="m", embedding_dim=1024)
    assert content.state is ContentState.READY
    assert (content.pages, content.text_key, content.chunker) == (3, pages_key(SHA), "c:v1")
    assert (content.embedding_model, content.embedding_dim) == ("m", 1024)


def test_content_fail_records_the_reason() -> None:
    content = processing_content()
    content.fail(UNREADABLE_PDF)
    assert content.state is ContentState.FAILED
    assert content.failure_reason == UNREADABLE_PDF


def test_only_processing_content_can_become_ready_or_failed() -> None:
    content = processing_content()
    content.ready(pages=1, text_key="k", chunker="c", embedding_model="m", embedding_dim=2)
    with pytest.raises(ContentStateError):
        content.ready(pages=1, text_key="k", chunker="c", embedding_model="m", embedding_dim=2)
    with pytest.raises(ContentStateError):
        content.fail("x")


def test_validate_chunk_returns_the_page() -> None:
    assert validate_chunk(3, "text") == 3
    assert validate_chunk(1, "x" * MAX_CHUNK_CHARS) == 1


@pytest.mark.parametrize(
    ("page", "text"),
    [(None, "t"), ("3", "t"), (True, "t"), (0, "t"), (1, "  \n"), (1, ""), (1, "x" * (MAX_CHUNK_CHARS + 1))],
)
def test_validate_chunk_refuses_bad_chunks(page: object, text: str) -> None:
    with pytest.raises(InvalidChunkError):
        validate_chunk(page, text)


def linked_document() -> Document:
    doc = new_document()
    doc.link_content(ContentId("c1"))
    return doc


def test_a_processed_document_waits_for_subjects() -> None:
    doc = linked_document()
    doc.await_subjects()
    assert doc.state is DocumentState.AWAITING_SUBJECTS and doc.subject_ids == []


def test_choosing_1_to_3_distinct_subjects_makes_it_ready() -> None:
    doc = linked_document()
    doc.await_subjects()
    doc.choose_subjects([SubjectId("s1"), SubjectId("s2")])
    assert (doc.state, doc.subject_ids) == (DocumentState.READY, ["s1", "s2"])
    doc.choose_subjects([SubjectId("s3")])  # a ready document accepts a new choice
    assert doc.subject_ids == ["s3"]


@pytest.mark.parametrize("ids", [[], ["s1", "s2", "s3", "s4"], ["s1", "s1"]])
def test_zero_more_than_three_or_duplicate_subjects_are_rejected(ids: list[str]) -> None:
    doc = linked_document()
    doc.await_subjects()
    with pytest.raises(InvalidSubjectsError):
        doc.choose_subjects([SubjectId(i) for i in ids])
    assert doc.state is DocumentState.AWAITING_SUBJECTS


def test_only_a_processed_document_accepts_subjects() -> None:
    doc = linked_document()  # still processing
    with pytest.raises(DocumentStateError):
        doc.choose_subjects([SubjectId("s1")])
    doc.fail("x")
    with pytest.raises(DocumentStateError):
        doc.choose_subjects([SubjectId("s1")])


def test_only_a_processing_document_with_content_can_wait_for_subjects() -> None:
    with pytest.raises(DocumentStateError):
        new_document().await_subjects()


def test_too_many_pages_reason_names_both_counts() -> None:
    assert too_many_pages(501, 500) == "This PDF has 501 pages; the limit is 500"


def test_display_title_prefers_override_then_content_title_then_file_name() -> None:
    d = new_document("file.pdf")
    assert d.title == "file.pdf"
    d.content_title = "Extracted"
    assert d.title == "Extracted"
    d.title_override = "Mine"
    assert d.title == "Mine"


def test_retry_puts_failed_content_back_to_processing_and_counts_the_attempt() -> None:
    content = Content.first_upload(ContentId("c1"), "a" * 64, 10, UserId("ada"))
    content.fail("This file isn't a readable PDF")
    content.retry(max_attempts=3)
    assert (content.state, content.attempts, content.failure_reason) == (ContentState.PROCESSING, 2, None)


def test_retry_is_refused_once_the_attempts_are_used_up() -> None:
    content = Content.first_upload(ContentId("c1"), "a" * 64, 10, UserId("ada"))
    for _ in range(2):
        content.fail("x")
        content.retry(max_attempts=3)
    content.fail("x")
    assert content.attempts == 3 and not content.can_retry(3)
    with pytest.raises(RetryLimitError, match="This file could not be processed"):
        content.retry(max_attempts=3)
    assert content.state is ContentState.FAILED


def test_only_failed_content_can_retry() -> None:
    content = Content.first_upload(ContentId("c1"), "a" * 64, 10, UserId("ada"))
    assert not content.can_retry(3)
    with pytest.raises(ContentStateError):
        content.retry(max_attempts=3)


def test_document_retry_returns_a_failed_document_to_processing() -> None:
    doc = Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), "a.pdf", NOW)
    doc.link_content(ContentId("c1"))
    doc.fail("This file isn't a readable PDF")
    doc.retry()
    assert (doc.state, doc.failure_reason) == (DocumentState.PROCESSING, None)


def test_only_a_failed_document_with_content_can_retry() -> None:
    doc = Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), "a.pdf", NOW)
    with pytest.raises(DocumentStateError):
        doc.retry()  # processing
    doc.fail("Duplicate uploads aren't supported yet")  # failed, but no content
    with pytest.raises(DocumentStateError):
        doc.retry()


def _listed(state: DocumentState, subjects: list[str], created_at: datetime) -> Document:
    doc = new_document()
    doc.state, doc.created_at = state, created_at
    doc.subject_ids = [SubjectId(s) for s in subjects]
    return doc


def test_an_empty_filter_matches_every_document() -> None:
    assert _listed(DocumentState.FAILED, [], NOW).matches(DocumentFilter())


def test_a_filter_matches_a_document_with_any_of_its_subjects() -> None:
    doc = _listed(DocumentState.READY, ["s1", "s2"], NOW)
    assert doc.matches(DocumentFilter(subject_ids=frozenset({SubjectId("s2"), SubjectId("s9")})))
    assert not doc.matches(DocumentFilter(subject_ids=frozenset({SubjectId("s9")})))
    no_subjects = _listed(DocumentState.PROCESSING, [], NOW)
    assert not no_subjects.matches(DocumentFilter(subject_ids=frozenset({SubjectId("s1")})))


def test_a_filter_matches_any_of_its_states() -> None:
    doc = _listed(DocumentState.READY, [], NOW)
    assert doc.matches(DocumentFilter(states=frozenset({DocumentState.READY, DocumentState.FAILED})))
    assert not doc.matches(DocumentFilter(states=frozenset({DocumentState.FAILED})))


def test_the_upload_range_includes_its_start_and_excludes_its_end() -> None:
    doc = _listed(DocumentState.READY, [], NOW)
    assert doc.matches(DocumentFilter(uploaded_from=NOW))
    assert not doc.matches(DocumentFilter(uploaded_from=NOW + timedelta(seconds=1)))
    assert doc.matches(DocumentFilter(uploaded_before=NOW + timedelta(seconds=1)))
    assert not doc.matches(DocumentFilter(uploaded_before=NOW))


def test_a_filter_needs_every_part_to_match() -> None:
    doc = _listed(DocumentState.READY, ["s1"], NOW)
    both = DocumentFilter(
        subject_ids=frozenset({SubjectId("s1")}),
        states=frozenset({DocumentState.READY}),
        uploaded_from=NOW - timedelta(days=1),
        uploaded_before=NOW + timedelta(days=1),
    )
    assert doc.matches(both)
    assert not doc.matches(replace(both, states=frozenset({DocumentState.FAILED})))
    assert not doc.matches(replace(both, uploaded_before=NOW))
