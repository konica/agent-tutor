"""The shared subject catalog: get-or-create by normalized name, unknown ids, embedding backfill (PRD §9.4, D20)."""

import uuid
from collections.abc import Callable, Collection

from langchain_core.embeddings import Embeddings

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject, clean_subject_name, normalize_subject_name
from smart_tutor.subjects.ports.subject_repository import SubjectRepository


class SubjectCatalogService:
    def __init__(
        self, repo: SubjectRepository, embeddings: Embeddings, new_id: Callable[[], str] = lambda: str(uuid.uuid4())
    ) -> None:
        self._repo = repo
        self._embeddings = embeddings
        self._new_id = new_id

    def get_or_create(self, name: str) -> SubjectId:
        """The subject with this name: an exact normalized match is reused, otherwise it is created and embedded."""
        cleaned = clean_subject_name(name)
        key = normalize_subject_name(cleaned)
        found = self._repo.find_by_normalized_names([key]).get(key)
        if found is not None:
            return found.subject_id
        [vector] = self._embeddings.embed_documents([cleaned])
        return self._repo.insert_or_get(Subject(SubjectId(self._new_id()), cleaned), key, vector).subject_id

    def unknown(self, subject_ids: Collection[SubjectId]) -> set[SubjectId]:
        return set(subject_ids) - set(self._repo.canonical_names(subject_ids))

    def embed_missing_names(self, batch: int = 100) -> int:
        """Embeds every subject that has no name embedding yet (the seeded General); returns how many."""
        done = 0
        while missing := self._repo.missing_name_embeddings(batch):
            vectors = self._embeddings.embed_documents([s.canonical_name for s in missing])
            for subject, vector in zip(missing, vectors, strict=True):
                self._repo.set_name_embedding(subject.subject_id, vector)
            done += len(missing)
        return done
