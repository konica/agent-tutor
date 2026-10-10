"""Fakes for processing a stored content: no pypdf, no text splitters, no Bedrock."""

from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from fakes.models import describing_chat_model, fake_embeddings
from smart_tutor.knowledge.application import DocumentDescriber, ProcessingTools, TooManyPagesError, UnreadablePdfError
from smart_tutor.knowledge.ports.pdf_extractor import PdfExtractor

CHUNK_CHARS = 100


class FakePdfExtractor(PdfExtractor):
    """`%PDF-x.y <text>` bytes: the text after the first space, split into pages on form feeds. Else unreadable."""

    def extract_pages(self, data: bytes, max_pages: int, first: int | None = None) -> list[str]:
        if not data.startswith(b"%PDF"):
            raise UnreadablePdfError("not a PDF")
        pages = data.decode("utf-8").partition(" ")[2].split("\f")
        if len(pages) > max_pages:
            raise TooManyPagesError(len(pages))
        return pages if first is None else pages[:first]


class PageChunker(BaseDocumentTransformer):
    """Splits each page into 100-character pieces and keeps the page's metadata."""

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        return [
            Document(page_content=d.page_content[i : i + CHUNK_CHARS], metadata={**d.metadata, "start_index": i})
            for d in documents
            for i in range(0, len(d.page_content), CHUNK_CHARS)
        ]


def fake_tools(
    dim: int = 8,
    extractor: PdfExtractor | None = None,
    chunker: BaseDocumentTransformer | None = None,
    embeddings: Embeddings | None = None,
    chat: BaseChatModel | None = None,
) -> ProcessingTools:
    return ProcessingTools(
        extractor=extractor or FakePdfExtractor(),
        describer=DocumentDescriber(chat or describing_chat_model()),
        chunker=chunker or PageChunker(),
        chunker_id="fake:100:v1",
        embeddings=embeddings or fake_embeddings(dim),
        embedding_model="fake-embedding",
        embedding_dim=dim,
    )
