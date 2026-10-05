"""Chunkers by configured method (ADR 0008): a LangChain document transformer plus an id stored with each chunk."""

import re
import unicodedata
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from smart_tutor.shared.config import ChunkingConfig


def clean_page_text(text: str) -> str:
    """Fold ligatures, rejoin words hyphenated across lines, and drop control characters except \\n and \\t."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) != "Cc")


class CleanedSplitter(BaseDocumentTransformer):
    """Cleans each page's text, then splits it; a chunk never spans pages and keeps its page's metadata."""

    def __init__(self, splitter: RecursiveCharacterTextSplitter) -> None:
        self._splitter = splitter

    def transform_documents(self, documents: Any, **kwargs: Any) -> list[Document]:
        cleaned = [Document(page_content=clean_page_text(d.page_content), metadata=dict(d.metadata)) for d in documents]
        return self._splitter.split_documents(cleaned)


def build_chunker(config: ChunkingConfig) -> tuple[BaseDocumentTransformer, str]:
    """The transformer for `config.method` and its chunker id (changes whenever chunking output would)."""
    if config.method == "recursive_character":
        params = {"chunk_size": 1000, "chunk_overlap": 200, **config.params}
        chunker_id = f"recursive_character:{params['chunk_size']}/{params['chunk_overlap']}:v1"
        return CleanedSplitter(RecursiveCharacterTextSplitter(**params)), chunker_id
    raise ValueError(f"Unknown chunking method: {config.method!r}")
