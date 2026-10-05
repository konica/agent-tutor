import json
from typing import Any

import pytest
from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.embeddings import Embeddings

from fakes import FakeObjectStore, FixedClock, InMemoryLibrary, fake_embeddings, fake_tools
from smart_tutor.knowledge.application import (
    ContentState,
    IngestionService,
    ProcessingTools,
    UnreadablePdfError,
    UploadService,
)
from smart_tutor.knowledge.domain.content import NO_TEXT_LAYER, UNREADABLE_PDF, pages_key
from smart_tutor.knowledge.domain.errors import InvalidChunkError
from smart_tutor.shared.domain.ids import ContentId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID

SENTENCE = "A sentence about attention mechanisms. " * 5  # 190 characters: two 100-character fake chunks


class World:
    def __init__(self, tools: ProcessingTools | None = None) -> None:
        self.library, self.objects = InMemoryLibrary(), FakeObjectStore()
        self.uploads = UploadService(self.library.unit_of_work, self.objects, FixedClock())
        self.tools = tools or fake_tools()
        self.ingestion = IngestionService(self.library.unit_of_work, self.objects, self.tools)

    def upload(self, data: bytes) -> tuple[str, str]:
        """Upload and ingest; returns the document id and the content id (processing already ran)."""
        started = self.uploads.start_upload(UserId("ada"), "paper.pdf")
        self.objects.objects[started.fields["key"]] = data
        self.ingestion.ingest_upload(started.fields["key"])
        return started.document_id, self.content_id()

    def content_id(self) -> str:
        [content] = self.library.state.contents.values()
        return content.content_id


def pdf(*pages: str) -> bytes:
    return b"%PDF-1.7 " + "\f".join(pages).encode()


def test_a_stored_pdf_becomes_chunks_pages_json_and_a_ready_document() -> None:
    w = World()
    document_id, content_id = w.upload(pdf(SENTENCE, SENTENCE))

    chunks = w.library.state.chunks[content_id]
    assert [(c.seq, c.page) for c in chunks] == [(0, 1), (1, 1), (2, 2), (3, 2)]
    assert all(c.content_id == content_id and len(c.embedding) == 8 for c in chunks)
    assert chunks[0].text == SENTENCE[:100]

    content = w.library.state.contents[content_id]
    assert content.state is ContentState.READY
    assert (content.pages, content.text_key, content.chunker) == (2, pages_key(content.sha256), "fake:100:v1")
    assert (content.embedding_model, content.embedding_dim) == ("fake-embedding", 8)
    assert content.failure_reason is None

    stored = w.objects.objects[pages_key(content.sha256)]
    assert json.loads(stored) == {"pages": [{"page": 1, "text": SENTENCE}, {"page": 2, "text": SENTENCE}]}
    assert w.objects.content_types[pages_key(content.sha256)] == "application/json"

    document = w.library.state.documents[document_id]
    assert (document.state, document.subject_ids) == ("ready", [GENERAL_SUBJECT_ID])


def test_blank_pages_make_no_chunks_and_pages_keep_physical_numbers() -> None:
    w = World()
    _, content_id = w.upload(pdf(SENTENCE, "  \n ", SENTENCE))

    assert {c.page for c in w.library.state.chunks[content_id]} == {1, 3}
    content = w.library.state.contents[content_id]
    assert content.pages == 3
    pages = json.loads(w.objects.objects[pages_key(content.sha256)])["pages"]
    assert [p["page"] for p in pages] == [1, 2, 3] and pages[1]["text"] == "  \n "


def test_unreadable_pdf_fails_content_and_document() -> None:
    w = World()
    document_id, content_id = w.upload(b"not a pdf at all")

    content = w.library.state.contents[content_id]
    assert (content.state, content.failure_reason) == (ContentState.FAILED, UNREADABLE_PDF)
    document = w.library.state.documents[document_id]
    assert (document.state, document.failure_reason) == ("failed", UNREADABLE_PDF)
    assert content_id not in w.library.state.chunks
    assert pages_key(content.sha256) not in w.objects.objects


def test_pdf_without_text_layer_fails() -> None:
    w = World()
    document_id, content_id = w.upload(pdf("", "", ""))

    content = w.library.state.contents[content_id]
    assert (content.state, content.failure_reason) == (ContentState.FAILED, NO_TEXT_LAYER)
    document = w.library.state.documents[document_id]
    assert (document.state, document.failure_reason) == ("failed", NO_TEXT_LAYER)
    assert content_id not in w.library.state.chunks
    assert pages_key(content.sha256) not in w.objects.objects


def test_processing_twice_keeps_one_set_of_chunks() -> None:
    w = World()
    _, content_id = w.upload(pdf(SENTENCE))
    before = w.library.state.chunks[content_id]

    assert w.ingestion.process_content(ContentId(content_id)) is None  # already ready: nothing to do
    assert w.library.state.chunks[content_id] == before

    # a crash between saving chunks and the message delete: chunks exist, content still processing
    w.library.state.contents[content_id].state = ContentState.PROCESSING
    assert w.ingestion.process_content(ContentId(content_id)) is ContentState.READY
    assert w.library.state.chunks[content_id] == before
    assert [c.seq for c in w.library.state.chunks[content_id]] == [0, 1]


class FailsOnce(Embeddings):
    """The first `embed_documents` call raises (Bedrock throttled); later calls work."""

    def __init__(self) -> None:
        self._inner, self.calls = fake_embeddings(8), 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Bedrock throttled")
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)


def test_redelivery_reprocesses_a_stored_content_that_is_still_processing() -> None:
    w = World(fake_tools(embeddings=FailsOnce()))
    started = w.uploads.start_upload(UserId("ada"), "paper.pdf")
    key = started.fields["key"]
    w.objects.objects[key] = pdf(SENTENCE)

    with pytest.raises(RuntimeError):
        w.ingestion.ingest_upload(key)
    document = w.library.state.documents[started.document_id]
    assert (document.state, document.content_id is not None) == ("processing", True)
    assert key not in w.objects.objects  # the upload copy was already removed

    assert w.ingestion.ingest_upload(key) is None  # SQS redelivers the same message
    assert w.library.state.documents[started.document_id].state == "ready"
    assert w.library.state.contents[w.content_id()].state is ContentState.READY


class BadChunker(BaseDocumentTransformer):
    def __init__(self, metadata: dict[str, Any], text: str) -> None:
        self._metadata, self._text = metadata, text

    def transform_documents(self, documents: Any, **kwargs: Any) -> list[Document]:
        return [Document(page_content=self._text, metadata=self._metadata)]


@pytest.mark.parametrize(
    ("metadata", "text"),
    [({}, "text"), ({"page": 0}, "text"), ({"page": 1}, "  "), ({"page": 1}, "x" * 8193)],
    ids=["no page", "page zero", "blank text", "too long"],
)
def test_invalid_chunker_output_is_rejected(metadata: dict[str, Any], text: str) -> None:
    w = World(fake_tools(chunker=BadChunker(metadata, text)))
    with pytest.raises(InvalidChunkError):
        w.upload(pdf(SENTENCE))
    [content] = w.library.state.contents.values()
    assert content.state is ContentState.PROCESSING
    assert w.library.state.chunks == {}


def test_wrong_embedding_dimension_crashes_and_stores_nothing() -> None:
    w = World(fake_tools(dim=8, embeddings=fake_embeddings(4)))
    with pytest.raises(ValueError, match="dimension"):
        w.upload(pdf(SENTENCE))
    [content] = w.library.state.contents.values()
    assert content.state is ContentState.PROCESSING
    assert w.library.state.chunks == {}


def test_an_unknown_content_is_ignored() -> None:
    assert World().ingestion.process_content(ContentId("nope")) is None


class FinishesElsewhere(Embeddings):
    """While this run embeds, a concurrent run finishes the content (the state flips under it)."""

    def __init__(self) -> None:
        self.library: InMemoryLibrary | None = None
        self._inner = fake_embeddings(8)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        assert self.library is not None
        [content] = self.library.state.contents.values()
        content.state = ContentState.READY
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)


def test_a_content_finished_by_another_run_is_left_alone_at_the_final_lock() -> None:
    embeddings = FinishesElsewhere()
    w = World(fake_tools(embeddings=embeddings))
    embeddings.library = w.library
    started = w.uploads.start_upload(UserId("ada"), "paper.pdf")
    w.objects.objects[started.fields["key"]] = pdf(SENTENCE)

    w.ingestion.ingest_upload(started.fields["key"])

    assert w.library.state.chunks == {}
    assert w.library.state.documents[started.document_id].state == "processing"


def test_a_content_finished_by_another_run_is_left_alone_when_failing() -> None:
    w = World()
    _, content_id = w.upload(pdf(SENTENCE))
    w.library.state.contents[content_id].state = ContentState.PROCESSING

    def finish_then_unreadable(data: bytes) -> list[str]:
        w.library.state.contents[content_id].state = ContentState.READY
        raise UnreadablePdfError("unreadable")

    w.tools.extractor.extract_pages = finish_then_unreadable  # type: ignore[method-assign]
    assert w.ingestion.process_content(ContentId(content_id)) is None
    assert w.library.state.contents[content_id].failure_reason is None
