"""In-memory subject catalog, seeded with General (no embedding, like the migration). Cosine similarity in Python."""

import math
from collections.abc import Collection, Sequence

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID, SubjectRepository
from smart_tutor.subjects.domain.subject import Subject, normalize_subject_name
from smart_tutor.subjects.domain.suggestions import Candidate


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


class InMemorySubjects(SubjectRepository):
    def __init__(
        self, names: dict[SubjectId, str] | None = None, embeddings: dict[SubjectId, list[float]] | None = None
    ) -> None:
        self.names = {GENERAL_SUBJECT_ID: "General"} if names is None else dict(names)
        self.embeddings = dict(embeddings or {})

    def canonical_names(self, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        return {s: self.names[s] for s in subject_ids if s in self.names}

    def most_similar(self, embedding: Sequence[float], limit: int) -> list[Candidate]:
        scored = [
            Candidate(Subject(sid, self.names[sid]), _cosine(embedding, vector))
            for sid, vector in self.embeddings.items()
            if sid in self.names
        ]
        return sorted(scored, key=lambda c: c.similarity, reverse=True)[:limit]

    def find_by_normalized_names(self, normalized: Collection[str]) -> dict[str, Subject]:
        wanted = set(normalized)
        found = {normalize_subject_name(name): Subject(sid, name) for sid, name in self.names.items()}
        return {key: subject for key, subject in found.items() if key in wanted}

    def insert_or_get(self, subject: Subject, normalized_name: str, name_embedding: Sequence[float]) -> Subject:
        existing = self.find_by_normalized_names([normalized_name]).get(normalized_name)
        if existing is not None:
            return existing
        self.names[subject.subject_id] = subject.canonical_name
        self.embeddings[subject.subject_id] = list(name_embedding)
        return subject

    def missing_name_embeddings(self, limit: int) -> list[Subject]:
        return [Subject(sid, name) for sid, name in self.names.items() if sid not in self.embeddings][:limit]

    def set_name_embedding(self, subject_id: SubjectId, embedding: Sequence[float]) -> None:
        self.embeddings[subject_id] = list(embedding)
