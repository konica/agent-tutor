import hashlib

import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, fake_tools
from smart_tutor.knowledge.application import IngestionService, StartedUpload, UploadOutcome, UploadService
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.shared.domain.ids import UserId

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


def test_a_new_file_is_stored_once_under_its_hash_and_the_upload_copy_removed() -> None:
    w = World()
    a = w.upload("ada")
    assert w.ingestion.ingest_upload(a.fields["key"]) is UploadOutcome.STORED
    assert set(w.objects.objects) == {f"contents/{SHA}.pdf", f"contents/{SHA}.pages.json"}
    assert w.objects.objects[f"contents/{SHA}.pdf"] == PDF
    [content] = w.library.state.contents.values()
    assert (content.sha256, content.size, content.state, content.processed_by_user_id) == (
        SHA,
        len(PDF),
        "ready",
        "ada",
    )
    doc = w.doc(a)
    assert (doc.content_id, doc.state) == (content.content_id, "awaiting_subjects")
    upload = w.library.state.uploads[a.upload_id]
    assert (upload.size, upload.outcome) == (len(PDF), UploadOutcome.STORED)


def test_another_learners_identical_file_fails_as_a_duplicate() -> None:
    w = World()
    a, b = w.upload("ada"), w.upload("bob")
    w.ingestion.ingest_upload(a.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is UploadOutcome.DUPLICATE
    assert len(w.library.state.contents) == 1
    doc = w.doc(b)
    assert (doc.state, doc.failure_reason, doc.content_id) == ("failed", "Duplicate uploads aren't supported yet", None)
    assert b.fields["key"] not in w.objects.objects
    assert w.library.state.uploads[b.upload_id].outcome is UploadOutcome.DUPLICATE


def test_same_learner_same_file_is_a_duplicate() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada", name="copy.pdf")
    w.ingestion.ingest_upload(first.fields["key"])
    assert w.ingestion.ingest_upload(second.fields["key"]) is UploadOutcome.DUPLICATE
    assert w.doc(second).state == "failed"


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
    a, b = w.upload("ada"), w.upload("bob")
    w.ingestion.ingest_upload(a.fields["key"])
    w.objects.objects[a.fields["key"]] = PDF  # S3 event redelivered; say the delete hadn't happened
    assert w.ingestion.ingest_upload(a.fields["key"]) is None
    assert w.doc(a).state == "awaiting_subjects" and w.doc(a).content_id is not None
    assert a.fields["key"] not in w.objects.objects
    w.ingestion.ingest_upload(b.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is None
    assert w.doc(b).failure_reason == "Duplicate uploads aren't supported yet"


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
    assert w.ingestion.ingest_upload(f"contents/{SHA}.pdf") is None


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
