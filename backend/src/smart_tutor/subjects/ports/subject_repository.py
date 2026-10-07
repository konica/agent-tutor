"""Access to the shared subject catalog."""

from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject
from smart_tutor.subjects.domain.suggestions import Candidate


class SubjectRepository(ABC):
    @abstractmethod
    def canonical_names(self, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        """Canonical name per known id; unknown ids are left out."""

    @abstractmethod
    def most_similar(self, embedding: Sequence[float], limit: int) -> list[Candidate]:
        """Subjects with a name embedding, by cosine similarity to `embedding`, highest first."""

    @abstractmethod
    def find_by_normalized_names(self, normalized: Collection[str]) -> dict[str, Subject]:
        """The subject per normalized name; names without a subject are left out."""

    @abstractmethod
    def insert_or_get(self, subject: Subject, normalized_name: str, name_embedding: Sequence[float]) -> Subject:
        """Insert unless the normalized name exists; concurrent callers get one row. Returns the stored subject."""

    @abstractmethod
    def search(self, normalized_query: str, exclude: Collection[SubjectId], limit: int) -> list[Subject]:
        """Subjects whose normalized name contains the query (matched literally): prefix matches first, then shorter
        names, then by name. Ids in `exclude` are left out."""

    @abstractmethod
    def missing_name_embeddings(self, limit: int) -> list[Subject]:
        """Subjects that have no name embedding yet (the seeded General row)."""

    @abstractmethod
    def set_name_embedding(self, subject_id: SubjectId, embedding: Sequence[float]) -> None:
        """Store the name embedding of one subject."""
