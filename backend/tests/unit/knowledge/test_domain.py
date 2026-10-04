from datetime import UTC, datetime

import pytest

from smart_tutor.knowledge.domain.content import Content, ContentState, content_key
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD, Document, DocumentState
from smart_tutor.knowledge.domain.errors import DocumentStateError, InvalidFileNameError
from smart_tutor.knowledge.domain.upload import Upload, parse_upload_key, upload_key
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId

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
    upload = Upload(UploadId("u1"), UserId("ada"), NOW)
    assert upload.key == upload_key(UserId("ada"), UploadId("u1")) == "uploads/ada/u1.pdf"
    assert parse_upload_key("uploads/ada/u1.pdf") == ("ada", "u1")


@pytest.mark.parametrize(
    "key", ["contents/x.pdf", "uploads/ada.pdf", "uploads/ada/u1.txt", "uploads/a/b/c.pdf", "uploads//u1.pdf"]
)
def test_other_keys_are_not_upload_keys(key: str) -> None:
    assert parse_upload_key(key) is None
