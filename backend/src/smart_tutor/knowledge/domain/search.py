"""A chunk found by search, with what a citation needs (PRD §9.3)."""

from dataclasses import dataclass

from smart_tutor.shared.domain.ids import DocumentId


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: str
    document_id: DocumentId
    document_title: str  # display title at read time (title_override, else file name until US-2b)
    page: int | None
    text: str
    score: float  # cosine similarity: 1 is identical
