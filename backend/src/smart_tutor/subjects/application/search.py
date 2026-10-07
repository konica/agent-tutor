"""Catalog search for the subject picker's type-ahead (PRD §8 US-2b, D20)."""

from collections.abc import Collection

from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application.subject_names import SubjectNames
from smart_tutor.subjects.domain.search import SEARCH_LIMIT, CatalogMatch, rank_matches
from smart_tutor.subjects.domain.subject import normalize_subject_name
from smart_tutor.subjects.ports.subject_repository import SubjectRepository


class SubjectSearch:
    def __init__(self, repo: SubjectRepository, names: SubjectNames, limit: int = SEARCH_LIMIT) -> None:
        self._repo = repo
        self._names = names
        self._limit = limit

    def search(self, user_id: UserId, query: str, learner_subject_ids: Collection[SubjectId]) -> list[CatalogMatch]:
        key = normalize_subject_name(query)
        if not key:
            return []
        yours = self._names.names_for(user_id, learner_subject_ids)
        shared = self._repo.search(key, exclude=yours.keys(), limit=self._limit)
        return rank_matches(key, yours, shared, self._limit)
