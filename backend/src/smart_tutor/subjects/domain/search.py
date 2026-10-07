"""Type-ahead over the shared subject catalog (PRD §8 US-2b): the learner's subjects first, then shared ones."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject, normalize_subject_name
from smart_tutor.subjects.domain.suggestions import SuggestionOrigin

SEARCH_LIMIT = 8


@dataclass(frozen=True)
class CatalogMatch:
    subject_id: SubjectId
    name: str
    origin: SuggestionOrigin  # YOURS or SHARED


def rank_matches(
    query: str, yours: Mapping[SubjectId, str], shared: Sequence[Subject], limit: int = SEARCH_LIMIT
) -> list[CatalogMatch]:
    """`yours` maps the learner's subjects to their display names; `shared` is already ordered by the catalog.

    Shared subjects the learner has are shown once, as theirs (by their name, never another learner's).
    """
    key = normalize_subject_name(query)
    if not key:
        return []
    mine = [(sid, name) for sid, name in yours.items() if key in normalize_subject_name(name)]
    mine.sort(key=lambda p: (not normalize_subject_name(p[1]).startswith(key), len(p[1]), p[1]))
    matches = [CatalogMatch(sid, name, SuggestionOrigin.YOURS) for sid, name in mine]
    matches += [
        CatalogMatch(s.subject_id, s.canonical_name, SuggestionOrigin.SHARED)
        for s in shared
        if s.subject_id not in yours
    ]
    return matches[:limit]
