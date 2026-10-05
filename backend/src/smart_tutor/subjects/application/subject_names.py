"""Subject names as a learner sees them."""

from collections.abc import Collection

from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.ports.subject_repository import SubjectRepository


class SubjectNames:
    def __init__(self, repo: SubjectRepository) -> None:
        self._repo = repo

    def names_for(self, user_id: UserId, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        """Display name per subject id: the canonical name for now.

        The learner's personal names (user_subject_names, US-10b) will take precedence over the
        canonical name when they exist (PRD §9.4); `user_id` is here for that.
        """
        return self._repo.canonical_names(subject_ids)
