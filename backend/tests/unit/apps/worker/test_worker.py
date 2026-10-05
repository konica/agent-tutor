import json

import pytest

from fakes import FakeObjectStore, FakeQueue, FixedClock, InMemoryLibrary, fake_tools
from smart_tutor.apps.worker.events import upload_keys
from smart_tutor.apps.worker.main import embedding_dimension, run_once
from smart_tutor.knowledge.application import IngestionService, UploadService
from smart_tutor.shared.domain.ids import UserId

PDF = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()


def s3_event(key: str, name: str = "ObjectCreated:Post") -> str:
    return json.dumps({"Records": [{"eventName": name, "s3": {"bucket": {"name": "b"}, "object": {"key": key}}}]})


def world() -> tuple[InMemoryLibrary, FakeObjectStore, UploadService, IngestionService]:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    return (
        library,
        objects,
        UploadService(library.unit_of_work, objects, FixedClock()),
        IngestionService(library.unit_of_work, objects, fake_tools()),
    )


def test_upload_keys_reads_created_events_and_decodes_keys() -> None:
    assert upload_keys(s3_event("uploads/ada/u+1%21.pdf")) == ["uploads/ada/u 1!.pdf"]
    assert upload_keys(s3_event("uploads/ada/u1.pdf", name="ObjectRemoved:Delete")) == []
    assert upload_keys(json.dumps({"Event": "s3:TestEvent"})) == []
    assert upload_keys("not json") == []


def test_an_upload_event_is_ingested_and_its_message_deleted() -> None:
    library, objects, uploads, ingestion = world()
    started = uploads.start_upload(UserId("ada"), "paper.pdf")
    objects.objects[started.fields["key"]] = PDF
    queue = FakeQueue(s3_event(started.fields["key"]))

    assert run_once(queue, ingestion) == 1
    assert queue.waiting == [] and len(queue.deleted) == 1
    assert library.state.documents[started.document_id].content_id is not None


def test_s3_test_event_is_deleted_without_ingesting() -> None:
    library, _, _, ingestion = world()
    queue = FakeQueue(json.dumps({"Event": "s3:TestEvent"}))
    run_once(queue, ingestion)
    assert len(queue.deleted) == 1 and library.commits == 0


def test_malformed_records_are_skipped_but_valid_ones_kept() -> None:
    body = json.dumps(
        {
            "Records": [
                {"eventName": "ObjectCreated:Put"},
                "junk",
                {"eventName": "ObjectCreated:Put", "s3": {"object": {"key": "uploads/ada/ok.pdf"}}},
            ]
        }
    )
    assert upload_keys('{"Records": [{"eventName": "ObjectCreated:Put"}, "junk"]}') == []
    assert upload_keys(body) == ["uploads/ada/ok.pdf"]


def test_a_failing_message_stays_for_redelivery() -> None:
    library, objects, uploads, ingestion = world()
    started = uploads.start_upload(UserId("ada"), "paper.pdf")
    objects.objects[started.fields["key"]] = PDF

    def broken(source_key: str, dest_key: str) -> None:
        raise RuntimeError("S3 down")

    objects.copy = broken  # type: ignore[method-assign]
    queue = FakeQueue(s3_event(started.fields["key"]))
    run_once(queue, ingestion)
    assert len(queue.waiting) == 1 and queue.deleted == []


def test_no_messages_is_fine() -> None:
    *_, ingestion = world()
    assert run_once(FakeQueue(), ingestion) == 0


def test_embedding_dimension_must_be_configured_and_match_the_column() -> None:
    assert embedding_dimension({"dimensions": 1024}) == 1024
    with pytest.raises(ValueError, match="params.dimensions"):
        embedding_dimension({})
    with pytest.raises(ValueError, match="1024"):
        embedding_dimension({"dimensions": 256})
