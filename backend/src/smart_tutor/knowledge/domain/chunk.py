"""A passage of a content's text with its embedding (PRD §9.4). Shared by every document of the content."""

from dataclasses import dataclass

from smart_tutor.knowledge.domain.errors import InvalidChunkError
from smart_tutor.shared.domain.ids import ContentId, DocumentId

MAX_CHUNK_CHARS = 8192


@dataclass(frozen=True)
class Chunk:
    content_id: ContentId
    seq: int  # output order of the chunker, from 0
    page: int | None
    text: str
    embedding: list[float]
    start_index: int | None = None  # offset in the page's cleaned text; None when unknown


@dataclass(frozen=True)
class StoredChunk:
    """A stored chunk without its embedding, as the start_index backfill reads it."""

    chunk_id: str
    seq: int
    page: int | None
    text: str
    start_index: int | None


@dataclass(frozen=True)
class ChunkPassage:
    """A cited chunk with the document it was read through, for the viewer's highlight."""

    chunk_id: str
    document_id: DocumentId
    page: int | None
    start_index: int | None  # offset in the page's cleaned text; None when unknown
    text: str


def start_index_of(value: object) -> int | None:
    """The splitter's start offset, or None when it couldn't find the chunk (it reports -1) or gave none."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def validate_chunk(page: object, text: str) -> int:
    """The chunk's page number, or `InvalidChunkError` when the chunker's output can't be cited or stored."""
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise InvalidChunkError("A chunk needs an integer page of 1 or more")
    if not text.strip():
        raise InvalidChunkError("A chunk needs text")
    if len(text) > MAX_CHUNK_CHARS:
        raise InvalidChunkError(f"A chunk has at most {MAX_CHUNK_CHARS} characters")
    return page
