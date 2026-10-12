"""Learner ratings sent on to where answers are traced (PRD §10.2): Phoenix, from #290."""

from abc import ABC, abstractmethod

from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating


class AnswerFeedback(ABC):
    @abstractmethod
    def send(self, run_id: RunId, rating: Rating) -> None:
        """Attach the learner's rating to the answer's run, replacing an earlier one. Must not block on the network;
        never given who rated."""


class NoAnswerFeedback(AnswerFeedback):
    """Ratings are only saved with the turn."""

    def send(self, run_id: RunId, rating: Rating) -> None:
        return None
