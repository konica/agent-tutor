"""A chunk the agent got back from search, with what its citation needs."""

from dataclasses import dataclass

from smart_tutor.shared.domain.citation import Citation


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_title: str
    page: int | None
    text: str
    score: float

    def citation(self) -> Citation:
        return Citation(chunk_id=self.chunk_id, document_title=self.document_title, page=self.page)
