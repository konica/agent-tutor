from collections.abc import Sequence
from typing import Any, ClassVar

import pytest
from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.messages import AIMessage

from fakes import (
    DESCRIPTION_ARGS,
    TEST_LIMITS,
    FakeObjectStore,
    FixedClock,
    InMemoryLibrary,
    describe_reply,
    describing_chat_model,
    fake_tools,
)
from fakes.models import FakeChatModel
from smart_tutor.knowledge.application import DocumentService, FileLimits, IngestionService, UploadService
from smart_tutor.knowledge.domain.content import Content, ContentState
from smart_tutor.shared.domain.ids import UserId

SENTENCE = "A sentence about attention mechanisms. " * 5
PRINTED_DOI = SENTENCE + "arXiv:1706.03762 doi:10.48550/arXiv.1706.03762"  # the fake model's DOI must be printed


def pdf(*pages: str) -> bytes:
    return b"%PDF-1.7 " + "\f".join(pages).encode()


class CountingModel(FakeChatModel):
    calls: ClassVar[int] = 0

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        CountingModel.calls += 1
        return super().invoke(input, config, **kwargs)


class CrashingChunker(BaseDocumentTransformer):
    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        raise RuntimeError("worker died during full extraction")


class World:
    def __init__(
        self,
        chat: FakeChatModel | None = None,
        chunker: BaseDocumentTransformer | None = None,
        limits: FileLimits = TEST_LIMITS,
    ) -> None:
        self.library, self.objects = InMemoryLibrary(), FakeObjectStore()
        self.uploads = UploadService(self.library.unit_of_work, self.objects, FixedClock(), TEST_LIMITS)
        self.ingestion = IngestionService(
            self.library.unit_of_work, self.objects, fake_tools(chat=chat, chunker=chunker), limits
        )
        self.documents = DocumentService(self.library.unit_of_work, max_attempts=3)

    def upload(self, data: bytes, name: str = "1706.03762v7.pdf") -> str:
        started = self.uploads.start_upload(UserId("ada"), name)
        self.objects.objects[started.fields["key"]] = data
        self.ingestion.ingest_upload(started.fields["key"])
        return started.fields["key"]

    def content(self) -> Content:
        [content] = self.library.state.contents.values()
        return content


def test_the_content_stores_the_description_embedding_and_work_key() -> None:
    w = World()
    w.upload(pdf(PRINTED_DOI, SENTENCE, SENTENCE))
    c = w.content()
    assert c.state is ContentState.READY
    assert (c.title, c.year, c.doi) == (DESCRIPTION_ARGS["title"], 2017, "10.48550/arxiv.1706.03762")
    assert c.authors == DESCRIPTION_ARGS["authors"]
    assert c.summary == DESCRIPTION_ARGS["summary"]
    assert c.proposed_subject_names == DESCRIPTION_ARGS["proposed_subject_names"]
    assert c.summary_embedding is not None and len(c.summary_embedding) == 8
    assert c.work_key == "doi:10.48550/arxiv.1706.03762"


def test_the_library_shows_the_extracted_title_while_processing() -> None:
    w = World(chunker=CrashingChunker())
    with pytest.raises(RuntimeError):
        w.upload(pdf(SENTENCE, SENTENCE))
    [view] = w.documents.list_documents(UserId("ada"))
    assert (view.state, view.title) == ("processing", DESCRIPTION_ARGS["title"])


def test_a_ready_document_keeps_the_extracted_title() -> None:
    w = World()
    w.upload(pdf(SENTENCE))
    [view] = w.documents.list_documents(UserId("ada"))
    assert (view.state, view.title) == ("ready", DESCRIPTION_ARGS["title"])


@pytest.mark.parametrize(
    "reply",
    [
        AIMessage(content="It's a paper about attention."),
        describe_reply(proposed_subject_names=["Only One"]),
    ],
)
def test_an_invalid_description_stores_nothing_and_processing_continues(reply: AIMessage) -> None:
    w = World(chat=describing_chat_model(reply))
    w.upload(pdf(SENTENCE))
    c = w.content()
    assert c.state is ContentState.READY
    assert (c.title, c.summary, c.summary_embedding, c.work_key) == (None, None, None, None)
    assert (c.authors, c.proposed_subject_names) == ([], [])
    [view] = w.documents.list_documents(UserId("ada"))
    assert (view.state, view.title) == ("ready", "1706.03762v7.pdf")


def test_an_invalid_doi_is_dropped_but_the_title_is_stored() -> None:
    w = World(chat=describing_chat_model(describe_reply(doi="not a doi")))
    w.upload(pdf(SENTENCE))
    c = w.content()
    assert c.state is ContentState.READY
    assert (c.title, c.doi) == (DESCRIPTION_ARGS["title"], None)
    assert c.work_key == f"title:attention is all you need:{DESCRIPTION_ARGS['year']}"


# The crash leaves the content processing; the redelivery re-runs process_content with a working chunker.
def test_redelivery_after_the_description_makes_no_second_model_call() -> None:
    CountingModel.calls = 0
    chat = CountingModel(messages=iter([describe_reply()]))  # a second call would raise
    w = World(chat=chat, chunker=CrashingChunker())
    with pytest.raises(RuntimeError):
        w.upload(pdf(SENTENCE))
    content_id = w.content().content_id
    retry = IngestionService(w.library.unit_of_work, w.objects, fake_tools(chat=chat), TEST_LIMITS)
    assert retry.process_content(content_id) is ContentState.READY
    assert CountingModel.calls == 1
    assert w.content().title == DESCRIPTION_ARGS["title"]


def test_a_pdf_over_the_page_limit_fails_before_any_model_call() -> None:
    CountingModel.calls = 0
    w = World(
        chat=CountingModel(messages=iter([describe_reply()])),
        limits=FileLimits(max_bytes=TEST_LIMITS.max_bytes, max_pages=2),
    )
    w.upload(pdf(SENTENCE, SENTENCE, SENTENCE))
    assert w.content().state is ContentState.FAILED
    assert CountingModel.calls == 0


def test_blank_first_pages_skip_the_model_call() -> None:
    CountingModel.calls = 0
    w = World(chat=CountingModel(messages=iter([describe_reply()])))
    w.upload(pdf(" ", "\n", SENTENCE, SENTENCE, SENTENCE, SENTENCE))
    assert CountingModel.calls == 0
    assert w.content().title is None


def test_the_model_sees_only_the_first_two_pages() -> None:
    seen: list[str] = []

    class Spy(FakeChatModel):
        def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            seen.append(str(input[-1].content))
            return super().invoke(input, config, **kwargs)

    w = World(chat=Spy(messages=iter([describe_reply()])))
    w.upload(pdf(*((name + " " + SENTENCE)[:200] for name in ("FIRST", "SECOND", "THIRD"))))
    assert "FIRST" in seen[0] and "SECOND" in seen[0] and "THIRD" not in seen[0]
