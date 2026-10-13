"""Training data for the topic-check model (spec 2026-10-13 §6.1–6.2): labeled messages, the train/eval split, and
threshold choice. Pure Python, so it is unit-tested without torch."""

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from evals.dataset import Example, in_eval_share, normalized
from smart_tutor.tutoring.application import topic_texts

STEPS = [step / 100 for step in range(50, 100)]  # thresholds tried, lowest first


@dataclass(frozen=True)
class Labeled:
    question: str
    previous: str | None
    off_topic: bool

    @property
    def texts(self) -> list[str]:
        """What the classifier scores (the same texts as the agent's adapter)."""
        return topic_texts(self.question, self.previous)


def labeled(example: Example) -> Labeled:
    history = example.inputs.get("history") or []
    previous = str(history[-1]["question"]) if history else None
    return Labeled(str(example.inputs["question"]), previous, bool(example.outputs["off_topic"]))


def split_train_eval(
    rows: Iterable[Labeled], hand_written: Iterable[str], share: float
) -> tuple[list[Labeled], list[Labeled]]:
    """(train, eval): the held-out share evaluates; a hand-written question never trains."""
    hand = {normalized(q) for q in hand_written}
    train: list[Labeled] = []
    evaluation: list[Labeled] = []
    for row in rows:
        if in_eval_share(row.question, share):
            evaluation.append(row)
        elif normalized(row.question) not in hand:
            train.append(row)
    return train, evaluation


def holdout(rows: Sequence[Labeled], share: float, seed: int) -> tuple[list[Labeled], list[Labeled]]:
    """(fit, held): a seeded shuffle; `held` picks the threshold and checks the export."""
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    cut = max(1, round(len(shuffled) * share))
    return shuffled[cut:], shuffled[:cut]


def training_rows(rows: Iterable[Labeled]) -> tuple[list[str], list[int]]:
    """Each message alone and with its previous question, labeled 1 when off-topic."""
    texts: list[str] = []
    labels: list[int] = []
    for row in rows:
        for text in row.texts:
            texts.append(text)
            labels.append(int(row.off_topic))
    return texts, labels


def rates(scored: Sequence[tuple[float, bool]], threshold: float) -> tuple[float, float]:
    """(false-rejection rate on on-topic messages, caught rate on off-topic messages) at `threshold`."""
    on = [p for p, off in scored if not off]
    off = [p for p, is_off in scored if is_off]
    rejected = sum(p >= threshold for p in on) / len(on) if on else 0.0
    caught = sum(p >= threshold for p in off) / len(off) if off else 0.0
    return rejected, caught


def pick_threshold(scored: Sequence[tuple[float, bool]], max_false_rejections: float = 0.005) -> float:
    """The lowest threshold (0.50 to 0.99 in steps of 0.01) whose false-rejection rate is at most
    `max_false_rejections`, leaving headroom under the 1% target; 0.99 when none is."""
    for threshold in STEPS:
        if rates(scored, threshold)[0] <= max_false_rejections + 1e-12:
            return threshold
    return STEPS[-1]
