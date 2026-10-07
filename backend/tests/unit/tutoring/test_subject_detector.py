"""SubjectDetector: one search over all of the learner's subjects, scored per subject (PRD §9.2 step 1)."""

import pytest

from fakes import FakeRetriever
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.application import DETECTION_K, DetectionPolicy, SubjectDetector
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

A, B, C = SubjectId("a"), SubjectId("b"), SubjectId("c")
POLICY = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.0625)


def chunk(score: float, *subjects: SubjectId) -> RetrievedChunk:
    return RetrievedChunk(f"c{score}", "a.pdf", 1, "text", score, subjects)


async def test_one_subject_is_bound_without_searching() -> None:
    retriever = FakeRetriever([chunk(0.9, A)])
    detection = await SubjectDetector(retriever, POLICY).detect("q", [A])
    assert detection.subject_ids == (A,) and not detection.unsure
    assert retriever.calls == []


async def test_searches_all_subjects_once_and_binds_the_clear_match() -> None:
    retriever = FakeRetriever([chunk(0.75, A), chunk(0.5, B), chunk(0.25, C)])
    detection = await SubjectDetector(retriever, POLICY).detect("What is attention?", [A, B, C])
    assert retriever.calls == [("What is attention?", [A, B, C], DETECTION_K)]
    assert detection.subject_ids == (A,) and not detection.unsure
    assert detection.scores == {A: 0.75, B: 0.5, C: 0.25}


async def test_binds_several_close_subjects() -> None:
    retriever = FakeRetriever([chunk(0.75, A, B), chunk(0.5, C)])
    detection = await SubjectDetector(retriever, POLICY).detect("q", [A, B, C])
    assert detection.subject_ids == (A, B) and not detection.unsure


async def test_unsure_falls_back_to_the_best_subject() -> None:
    retriever = FakeRetriever([chunk(0.75, B), chunk(0.65625, A)])  # A: outside multi_margin, inside detect_margin
    detection = await SubjectDetector(retriever, POLICY).detect("q", [A, B])
    assert detection.subject_ids == (B,) and detection.unsure


async def test_no_hits_falls_back_to_the_first_subject() -> None:
    detection = await SubjectDetector(FakeRetriever([]), POLICY).detect("q", [B, A])
    assert detection.subject_ids == (B,) and detection.unsure and detection.scores == {}


async def test_no_subjects_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        await SubjectDetector(FakeRetriever([]), POLICY).detect("q", [])
