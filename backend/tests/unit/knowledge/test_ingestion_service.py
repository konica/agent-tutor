import hashlib

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, fake_tools
from smart_tutor.knowledge.application import (
    IngestionService,
    StartedUpload,
    UploadOutcome,
    UploadService,
    UploadStatus,
)
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.shared.domain.ids import UploadId, UserId

PDF = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
SHA = hashlib.sha256(PDF).hexdigest()


class World:
    def __init__(self) -> None:
        self.library, self.objects = InMemoryLibrary(), FakeObjectStore()
        self.uploads = UploadService(self.library.unit_of_work, self.objects, FixedClock(), TEST_LIMITS)
        self.ingestion = IngestionService(self.library.unit_of_work, self.objects, fake_tools(), TEST_LIMITS)

    def upload(self, user: str, data: bytes = PDF, name: str = "paper.pdf") -> StartedUpload:
        started = self.uploads.start_upload(UserId(user), name)
        self.objects.objects[started.fields["key"]] = data  # what the browser's POST does
        return started

    def doc(self, started: StartedUpload) -> Document:
        return self.library.state.documents[started.document_id]


def key(user: str, content_id: str, suffix: str = "pdf") -> str:
    return f"contents/{user}/{content_id}.{suffix}"


def test_a_new_file_is_stored_under_its_owner_and_the_upload_copy_removed() -> None:
    w = World()
    a = w.upload("ada")
    assert w.ingestion.ingest_upload(a.fields["key"]) is UploadOutcome.STORED
    [content] = w.library.state.contents.values()
    assert set(w.objects.objects) == {key("ada", content.content_id), key("ada", content.content_id, "pages.json")}
    assert w.objects.objects[key("ada", content.content_id)] == PDF
    assert (content.sha256, content.size, content.state, content.owner_id) == (SHA, len(PDF), "ready", "ada")
    doc = w.doc(a)
    assert (doc.content_id, doc.state) == (content.content_id, "awaiting_subjects")
    upload = w.library.state.uploads[a.upload_id]
    assert (upload.size, upload.outcome, upload.document_id) == (len(PDF), UploadOutcome.STORED, a.document_id)


def test_each_chunk_keeps_its_offset_in_its_pages_text() -> None:
    w = World()
    a = w.upload("ada", b"%PDF-1.7 " + b"x" * 250)
    w.ingestion.ingest_upload(a.fields["key"])
    [content] = w.library.state.contents.values()
    assert [(c.page, c.start_index) for c in w.library.state.chunks[content.content_id]] == [(1, 0), (1, 100), (1, 200)]


def test_another_learners_identical_file_is_their_own_content() -> None:
    w = World()
    a, b = w.upload("ada"), w.upload("bob")
    w.ingestion.ingest_upload(a.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is UploadOutcome.STORED
    contents = sorted(w.library.state.contents.values(), key=lambda c: c.owner_id)
    assert [(c.owner_id, c.sha256, c.state) for c in contents] == [("ada", SHA, "ready"), ("bob", SHA, "ready")]
    assert contents[0].content_id != contents[1].content_id
    assert all(w.library.state.chunks[c.content_id] for c in contents)  # each embedded in full
    assert (w.doc(a).state, w.doc(b).state) == ("awaiting_subjects", "awaiting_subjects")
    assert w.doc(b).content_id == contents[1].content_id


def test_the_same_learners_duplicate_points_to_their_document() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada", name="copy.pdf")
    w.ingestion.ingest_upload(first.fields["key"])
    chunks_before = dict(w.library.state.chunks)
    assert w.ingestion.ingest_upload(second.fields["key"]) is UploadOutcome.DUPLICATE
    assert second.document_id not in w.library.state.documents  # no second document
    assert len(w.library.state.contents) == 1 and w.library.state.chunks == chunks_before
    assert second.fields["key"] not in w.objects.objects
    upload = w.library.state.uploads[second.upload_id]
    assert (upload.outcome, upload.document_id) == (UploadOutcome.DUPLICATE, first.document_id)


def test_redelivery_after_a_duplicate_deletes_the_leftover_upload() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada")
    w.ingestion.ingest_upload(first.fields["key"])
    w.ingestion.ingest_upload(second.fields["key"])
    w.objects.objects[second.fields["key"]] = PDF  # say the delete hadn't happened
    assert w.ingestion.ingest_upload(second.fields["key"]) is None
    assert second.fields["key"] not in w.objects.objects
    assert len(w.library.state.contents) == 1


def test_upload_status_reports_the_outcome_only_to_its_learner() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada")
    pending = w.uploads.upload_status(UserId("ada"), second.upload_id)
    assert pending == UploadStatus(None, None, False)
    w.ingestion.ingest_upload(first.fields["key"])
    w.ingestion.ingest_upload(second.fields["key"])
    assert w.uploads.upload_status(UserId("ada"), second.upload_id) == UploadStatus(
        UploadOutcome.DUPLICATE, first.document_id, False
    )
    assert w.uploads.upload_status(UserId("bob"), second.upload_id) is None
    assert w.uploads.upload_status(UserId("ada"), UploadId("00000000-0000-4000-8000-000000000000")) is None


def test_different_bytes_make_different_contents() -> None:
    w = World()
    a, b = (
        w.upload("ada"),
        w.upload("ada", data=b"%PDF-1.7 " + ("Another sentence about gradient descent. " * 5).encode()),
    )
    w.ingestion.ingest_upload(a.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is UploadOutcome.STORED
    assert len(w.library.state.contents) == 2


def test_redelivery_after_success_changes_nothing() -> None:
    w = World()
    a = w.upload("ada")
    w.ingestion.ingest_upload(a.fields["key"])
    w.objects.objects[a.fields["key"]] = PDF  # S3 event redelivered; say the delete hadn't happened
    assert w.ingestion.ingest_upload(a.fields["key"]) is None
    assert w.doc(a).state == "awaiting_subjects" and w.doc(a).content_id is not None
    assert a.fields["key"] not in w.objects.objects


def test_key_owner_mismatch_is_skipped() -> None:
    w = World()
    a = w.upload("ada")
    forged = f"uploads/bob/{a.upload_id}.pdf"
    w.objects.objects[forged] = PDF
    assert w.ingestion.ingest_upload(forged) is None
    assert w.doc(a).awaiting_upload
    assert w.library.state.contents == {}


def test_unknown_upload_and_non_upload_keys_are_skipped() -> None:
    w = World()
    assert w.ingestion.ingest_upload("uploads/ada/nope.pdf") is None
    assert w.ingestion.ingest_upload("contents/ada/c1.pdf") is None


def test_a_missing_upload_object_is_skipped_and_the_document_still_waits() -> None:
    w = World()
    a = w.uploads.start_upload(UserId("ada"), "paper.pdf")  # browser never POSTed
    assert w.ingestion.ingest_upload(a.fields["key"]) is None
    assert w.doc(a).awaiting_upload


def test_a_failure_before_commit_leaves_the_upload_for_a_retry() -> None:
    w = World()
    a = w.upload("ada")

    def broken_copy(source_key: str, dest_key: str) -> None:
        raise RuntimeError("S3 down")

    w.objects.copy = broken_copy  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        w.ingestion.ingest_upload(a.fields["key"])
    assert w.library.state.contents == {}
    assert w.doc(a).awaiting_upload
    assert a.fields["key"] in w.objects.objects


def test_a_redelivery_after_a_failed_commit_reuses_the_content_key(monkeypatch: pytest.MonkeyPatch) -> None:
    w = World()
    a = w.upload("ada")
    unit_of_work = type(w.library.unit_of_work())
    real_commit = unit_of_work.commit

    def failing_commit(self: object) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(unit_of_work, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        w.ingestion.ingest_upload(a.fields["key"])  # the PDF was copied, then the commit failed
    monkeypatch.setattr(unit_of_work, "commit", real_commit)
    assert w.ingestion.ingest_upload(a.fields["key"]) is UploadOutcome.STORED
    [content] = w.library.state.contents.values()
    pdfs = [k for k in w.objects.objects if k.startswith("contents/ada/") and k.endswith(".pdf")]
    assert pdfs == [key("ada", content.content_id)]
