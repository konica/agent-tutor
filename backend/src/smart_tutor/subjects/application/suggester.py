"""Three subject suggestions for a learner's content (PRD §9.2 step 5, D20, US-2b)."""

from collections.abc import Collection, Sequence

from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application.subject_names import SubjectNames
from smart_tutor.subjects.domain.subject import GENERAL_SUBJECT_ID, Subject, normalize_subject_name
from smart_tutor.subjects.domain.suggestions import MATCH_THRESHOLD, YOURS_BOOST, Suggestion, rank_suggestions
from smart_tutor.subjects.ports.subject_repository import SubjectRepository


class SubjectSuggester:
    def __init__(
        self,
        repo: SubjectRepository,
        names: SubjectNames,
        threshold: float = MATCH_THRESHOLD,
        boost: float = YOURS_BOOST,
        nearest: int = 10,
    ) -> None:
        self._repo = repo
        self._names = names
        self._threshold = threshold
        self._boost = boost
        self._nearest = nearest

    def suggest(
        self,
        user_id: UserId,
        summary_embedding: Sequence[float] | None,
        proposed_names: Sequence[str],
        learner_subject_ids: Collection[SubjectId],
    ) -> list[Suggestion]:
        similar = self._repo.most_similar(summary_embedding, self._nearest) if summary_embedding else []
        existing = self._repo.find_by_normalized_names({normalize_subject_name(n) for n in proposed_names})
        yours = self._names.names_for(user_id, learner_subject_ids)
        general_name = self._names.names_for(user_id, [GENERAL_SUBJECT_ID]).get(GENERAL_SUBJECT_ID, "General")
        return rank_suggestions(
            similar=similar,
            proposed_names=proposed_names,
            existing_by_name=existing,
            yours=yours,
            fallback=Subject(GENERAL_SUBJECT_ID, general_name),
            threshold=self._threshold,
            boost=self._boost,
        )
