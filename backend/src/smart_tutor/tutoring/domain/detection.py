"""Subject detection (PRD §9.2 step 1): which of the learner's subjects a first question clearly matches."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import MAX_SUBJECTS


def best_scores(chunks: Iterable[RetrievedChunk], among: Collection[SubjectId]) -> dict[SubjectId, float]:
    """Each asked-about subject's best chunk similarity; subjects without a chunk are absent."""
    asked = set(among)
    scores: dict[SubjectId, float] = {}
    for chunk in chunks:
        for subject_id in chunk.subject_ids:
            if subject_id in asked and chunk.score > scores.get(subject_id, float("-inf")):
                scores[subject_id] = chunk.score
    return scores


@dataclass(frozen=True)
class DetectionPolicy:
    """Thresholds are settings (SSM), tuned on the detection dataset (PRD §10.3)."""

    detect_threshold: float
    detect_margin: float
    multi_margin: float

    def ranked(self, scores: Mapping[SubjectId, float]) -> list[SubjectId]:
        """Highest score first; ties by subject id, so detection is deterministic."""
        return sorted(scores, key=lambda s: (-scores[s], s))

    def bind(self, scores: Mapping[SubjectId, float]) -> tuple[SubjectId, ...] | None:
        """The 1–3 subjects the question clearly matches, or None when unsure.

        Bound: every subject at or above the threshold and within `multi_margin` of the best (at most 3). They must
        lead the runner-up, the best subject not bound, by at least `detect_margin`.
        """
        ranked = self.ranked(scores)
        if not ranked or scores[ranked[0]] < self.detect_threshold:
            return None
        best = scores[ranked[0]]
        close = [s for s in ranked if scores[s] >= self.detect_threshold and best - scores[s] <= self.multi_margin]
        bound = close[:MAX_SUBJECTS]
        rest = ranked[len(bound) :]
        if rest and best - scores[rest[0]] < self.detect_margin:
            return None
        return tuple(bound)


@dataclass(frozen=True)
class Detection:
    """The subjects a new thread starts with; `unsure`: none bound; the learner picks."""

    subject_ids: tuple[SubjectId, ...]
    unsure: bool
    scores: Mapping[SubjectId, float] = field(default_factory=dict)
