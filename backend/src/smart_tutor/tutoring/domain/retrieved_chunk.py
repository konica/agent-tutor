"""A chunk the agent got back from search, with what its citation needs."""

from dataclasses import dataclass

from smart_tutor.shared.domain.citation import Citation
from smart_tutor.shared.domain.ids import SubjectId


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_title: str
    page: int | None
    text: str
    score: float
    subject_ids: tuple[SubjectId, ...] = ()  # which of the searched subjects it belongs to

    def citation(self, n: int | None = None) -> Citation:
        return Citation(chunk_id=self.chunk_id, document_title=self.document_title, page=self.page, n=n)
