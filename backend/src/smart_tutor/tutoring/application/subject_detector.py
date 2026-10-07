"""Detect a new thread's subjects from its first question (PRD §9.2 step 1, US-3)."""

from collections.abc import Sequence

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.detection import Detection, DetectionPolicy, best_scores
from smart_tutor.tutoring.ports.retriever import Retriever

DETECTION_K = 20  # one search over all of the learner's subjects; each subject scores its best chunk


class SubjectDetector:
    def __init__(self, retriever: Retriever, policy: DetectionPolicy) -> None:
        self._retriever = retriever
        self._policy = policy

    async def detect(self, question: str, learner_subjects: Sequence[SubjectId]) -> Detection:
        if not learner_subjects:
            raise ValueError("detection needs the learner's subjects")
        if len(learner_subjects) == 1:  # learners with one subject skip detection
            return Detection((learner_subjects[0],), unsure=False)
        chunks = await self._retriever.search(question, learner_subjects, DETECTION_K)
        scores = best_scores(chunks, among=learner_subjects)
        bound = self._policy.bind(scores)
        if bound is not None:
            return Detection(bound, unsure=False, scores=scores)
        return Detection((), unsure=True, scores=scores)  # the learner picks
