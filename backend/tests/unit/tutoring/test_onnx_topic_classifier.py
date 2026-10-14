"""The SetFit topic classifier on onnxruntime (spec 2026-10-13 §5.2), against the fixture model in fakes.topic_model."""

from pathlib import Path

import pytest

from fakes import write_topic_model
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier
from smart_tutor.tutoring.application import HistoryTurn

ON, OFF = 0.0180, 0.9820  # sigmoid(-4), sigmoid(4)


def classifier(tmp_path: Path, **kw: object) -> OnnxSetFitTopicClassifier:
    return OnnxSetFitTopicClassifier(write_topic_model(tmp_path / "model", **kw))  # type: ignore[arg-type]


def test_study_and_off_topic_texts_score_apart(tmp_path: Path) -> None:
    scores = classifier(tmp_path).p_off_topic(["Explain photosynthesis", "Tell me a joke"])
    assert scores == [pytest.approx(ON, abs=1e-3), pytest.approx(OFF, abs=1e-3)]


async def test_a_first_question_is_scored_alone(tmp_path: Path) -> None:
    verdict = await classifier(tmp_path).classify("Tell me a joke", [])
    assert verdict.p_off_topic == pytest.approx(OFF, abs=1e-3) and verdict.model == "fixture@1"


async def test_context_can_rescue_a_question_the_verdict_is_the_lowest_score(tmp_path: Path) -> None:
    # Alone "Tell me a joke" is off-topic; with a study question before it the pair scores 0.5. The lower wins.
    verdict = await classifier(tmp_path).classify("Tell me a joke", [HistoryTurn("Explain photosynthesis", "…")])
    assert verdict.p_off_topic == pytest.approx(0.5, abs=1e-3)


async def test_an_off_topic_previous_turn_cannot_sink_a_study_question(tmp_path: Path) -> None:
    verdict = await classifier(tmp_path).classify("Explain photosynthesis", [HistoryTurn("Tell me a joke", "…")])
    assert verdict.p_off_topic == pytest.approx(ON, abs=1e-3)


def test_cls_pooling_reads_the_first_token_and_mean_pooling_all(tmp_path: Path) -> None:
    text = ["Tell explain explain"]
    assert classifier(tmp_path / "cls", pooling="cls").p_off_topic(text)[0] > 0.95
    assert classifier(tmp_path / "mean", pooling="mean").p_off_topic(text)[0] < 0.2


def test_without_normalization_the_raw_pooled_vector_is_scored(tmp_path: Path) -> None:
    # mean of tell, me, a, joke = [0, 0.5]: logit 2 → 0.881 (normalized it would be [0, 1] → 0.982)
    assert classifier(tmp_path, normalize=False).p_off_topic(["Tell me a joke"])[0] == pytest.approx(0.8808, abs=1e-3)


def test_long_text_is_cut_to_max_tokens(tmp_path: Path) -> None:
    score = classifier(tmp_path, max_tokens=2).p_off_topic(["Explain photosynthesis tell joke tell joke"])[0]
    assert score == pytest.approx(ON, abs=1e-3)


def test_the_default_threshold_is_the_manifests(tmp_path: Path) -> None:
    assert classifier(tmp_path, threshold=0.73).default_threshold == 0.73


def test_a_manifest_with_an_unknown_pooling_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pooling"):
        classifier(tmp_path, pooling="max")


def test_a_head_that_is_not_binary_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="binary"):
        classifier(tmp_path, head_rows=2)


def test_a_missing_model_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        OnnxSetFitTopicClassifier(tmp_path / "missing")
