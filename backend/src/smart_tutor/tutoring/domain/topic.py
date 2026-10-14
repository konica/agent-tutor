"""The topic check (PRD §9.2 step 0, spec 2026-10-13): whether a question is off-topic for a study tutor, as a
probability from a decision model. The texts a classifier scores are built here, so training (backend/evals) and the
agent build them the same way."""

from collections.abc import Sequence
from dataclasses import dataclass

from smart_tutor.tutoring.domain.turn import HistoryTurn


@dataclass(frozen=True)
class TopicVerdict:
    p_off_topic: float  # 0..1
    model: str  # the model and its version, for traces

    def is_off_topic(self, threshold: float) -> bool:
        return self.p_off_topic >= threshold


def topic_texts(question: str, previous_question: str | None = None) -> list[str]:
    """The question alone, then with the previous question when there is one. A classifier scores each and the
    verdict is the lowest (on-topic wins): context rescues a terse follow-up, and an off-topic previous turn can't sink
    a study question."""
    texts = [question]
    if previous_question:
        texts.append(f"Previous question: {previous_question}\nQuestion: {question}")
    return texts


def previous_question(history: Sequence[HistoryTurn]) -> str | None:
    return history[-1].question if history else None
