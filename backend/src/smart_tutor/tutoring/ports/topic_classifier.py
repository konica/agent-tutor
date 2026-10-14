"""Decide whether a question is off-topic (PRD §9.2 step 0). Adapters: a SetFit model on onnxruntime
(OnnxSetFitTopicClassifier); later possibly another decision model, such as TypeSafe's Jev (spec 2026-10-13 §5.4)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from smart_tutor.tutoring.domain.topic import TopicVerdict
from smart_tutor.tutoring.domain.turn import HistoryTurn


class TopicClassifier(ABC):
    @property
    @abstractmethod
    def default_threshold(self) -> float:
        """The threshold tuned for this model; configuration may override it."""

    @abstractmethod
    async def classify(self, question: str, history: Sequence[HistoryTurn]) -> TopicVerdict:
        """P(off-topic) of the question, given the conversation's earlier turns, oldest first. May raise anything: the
        caller fails open."""
