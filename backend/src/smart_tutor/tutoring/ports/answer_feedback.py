"""Learner ratings sent on to where answers are traced (PRD §10.2): none yet; #318 sends them to Langfuse as scores."""

from abc import ABC, abstractmethod

from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating


class AnswerFeedback(ABC):
    @abstractmethod
    def send(self, run_id: RunId, rating: Rating) -> None:
        """Attach the learner's rating to the answer's run, replacing an earlier one. Must not block on the network;
        never given who rated."""

    @abstractmethod
    def clear(self, run_id: RunId) -> None:
        """Remove the run's rating (a learner un-rating a turn; not offered yet, PRD §10.2). Must not block on the
        network."""

    def close(self) -> None:
        """Process shutdown: drop work not yet sent and release what the adapter holds. Nothing by default."""
        return None


class NoAnswerFeedback(AnswerFeedback):
    """Ratings are only saved with the turn."""

    def send(self, run_id: RunId, rating: Rating) -> None:
        return None

    def clear(self, run_id: RunId) -> None:
        return None
