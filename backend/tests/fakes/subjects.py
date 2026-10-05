"""In-memory subject catalog, seeded with General."""

from collections.abc import Collection

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID, SubjectRepository


class InMemorySubjects(SubjectRepository):
    def __init__(self, names: dict[SubjectId, str] | None = None) -> None:
        self.names = {GENERAL_SUBJECT_ID: "General"} if names is None else dict(names)

    def canonical_names(self, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        return {s: self.names[s] for s in subject_ids if s in self.names}
