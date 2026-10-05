"""Read access to the shared subject catalog."""

from abc import ABC, abstractmethod
from collections.abc import Collection

from smart_tutor.shared.domain.ids import SubjectId


class SubjectRepository(ABC):
    @abstractmethod
    def canonical_names(self, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        """Canonical name per known id; unknown ids are left out."""
