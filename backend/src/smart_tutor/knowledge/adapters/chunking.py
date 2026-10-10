"""Chunkers by configured method (ADR 0008): a LangChain document transformer plus an id stored with each chunk."""

from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from smart_tutor.knowledge.domain.page_text import clean_page_text
from smart_tutor.shared.config import ChunkingConfig

__all__ = ["CleanedSplitter", "build_chunker", "clean_page_text"]


class CleanedSplitter(BaseDocumentTransformer):
    """Cleans each page's text, then splits it; a chunk never spans pages and keeps its page's metadata."""

    def __init__(self, splitter: RecursiveCharacterTextSplitter) -> None:
        self._splitter = splitter

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        cleaned = [Document(page_content=clean_page_text(d.page_content), metadata=dict(d.metadata)) for d in documents]
        return self._splitter.split_documents(cleaned)


def build_chunker(config: ChunkingConfig) -> tuple[BaseDocumentTransformer, str]:
    """The transformer for `config.method` and its chunker id (changes whenever chunking output would)."""
    if config.method == "recursive_character":
        params = {**ChunkingConfig().params, **config.params}
        size, overlap = params["chunk_size"], params["chunk_overlap"]
        # ADR 0008 separators: paragraph, line, sentence end, word, character (the library default lacks ". ").
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
            is_separator_regex=False,
            # metadata["start_index"]: the chunk's offset in the cleaned page text (the viewer's highlight, PRD §9.4)
            add_start_index=True,
        )
        return CleanedSplitter(splitter), f"recursive_character:{size}/{overlap}:v1"
    raise ValueError(f"Unknown chunking method: {config.method!r}")
