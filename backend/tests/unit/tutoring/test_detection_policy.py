"""DetectionPolicy (PRD §9.2 step 1): bind 1–3 subjects from per-subject best scores, or be unsure."""

import pytest

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.detection import DetectionPolicy, best_scores
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

A, B, C, D = (SubjectId(x) for x in "abcd")
POLICY = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.0625)


@pytest.mark.parametrize(
    ("scores", "bound"),
    [
        ({}, None),
        ({A: 0.75}, (A,)),  # no runner-up
        ({A: 0.5}, (A,)),  # exactly at the threshold
        ({A: 0.4375}, None),  # just below the threshold
        ({A: 0.75, B: 0.625}, (A,)),  # leads by exactly detect_margin
        ({A: 0.75, B: 0.65625}, None),  # leads by less than detect_margin, more than multi_margin
        ({A: 0.75, B: 0.6875, C: 0.5}, (A, B)),  # B exactly at multi_margin; runner-up C leads by 0.25
        ({A: 0.75, B: 0.6875, C: 0.6875}, (A, B, C)),
        ({A: 0.75, B: 0.6875, C: 0.625}, (A, B)),  # C outside multi_margin, exactly detect_margin behind
        ({A: 0.75, B: 0.6875, C: 0.65625}, None),  # C outside multi_margin but too close
        ({A: 0.5, B: 0.4375}, None),  # B is under the threshold, so it's the runner-up, 0.0625 behind
        ({A: 0.53125, B: 0.40625}, (A,)),
    ],
)
def test_binds_or_is_unsure(scores: dict[SubjectId, float], bound: tuple[SubjectId, ...] | None) -> None:
    assert POLICY.bind(scores) == bound


def test_never_binds_more_than_three() -> None:
    wide = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.25)
    assert wide.bind({A: 0.875, B: 0.8125, C: 0.75, D: 0.625}) == (A, B, C)  # D leads by 0.25 ≥ 0.125


def test_a_fourth_close_subject_makes_it_unsure() -> None:
    assert POLICY.bind({A: 0.75, B: 0.75, C: 0.75, D: 0.75}) is None


def test_a_multi_margin_wider_than_the_threshold_still_needs_the_threshold() -> None:
    wide = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.5)
    assert wide.bind({A: 0.75, B: 0.375}) == (A,)  # B within multi_margin but under the threshold; leads by 0.375


def test_ties_rank_by_subject_id() -> None:
    assert POLICY.ranked({B: 0.5, A: 0.5, C: 0.75}) == [C, A, B]


def test_best_scores_keeps_each_subjects_best_chunk_among_the_asked_subjects() -> None:
    chunks = [
        RetrievedChunk("c1", "a.pdf", 1, "x", 0.9, (A, B)),
        RetrievedChunk("c2", "b.pdf", 1, "y", 0.7, (B,)),
        RetrievedChunk("c3", "c.pdf", 1, "z", 0.95, (D,)),  # not asked about: ignored
    ]
    assert best_scores(chunks, among=[A, B, C]) == {A: 0.9, B: 0.9}
