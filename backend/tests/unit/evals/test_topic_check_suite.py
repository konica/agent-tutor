"""The topic_check suite (spec 2026-10-13 §6.3): the classifier alone: false rejections, off-topic caught."""

from pathlib import Path

from evals.evaluators.topic_check import SUITE, false_rejections, off_topic_caught
from evals.targets import TopicCheckTarget
from fakes import FakeTopicClassifier, write_topic_model
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier

ON, OFF = {"off_topic": False, "kind": "subject_concept"}, {"off_topic": True, "kind": "entertainment"}


async def test_the_target_reports_the_verdict_with_the_history_given() -> None:
    classifier = FakeTopicClassifier({"Tell me a joke.": 0.9})
    target = TopicCheckTarget(classifier, 0.5)
    out = await target({"question": "Tell me a joke.", "history": [{"question": "Earlier?", "answer": ""}]})
    assert out == {"off_topic": True, "p_off_topic": 0.9, "model": "fake@1"}
    [(question, history)] = classifier.calls
    assert question == "Tell me a joke." and [h.question for h in history] == ["Earlier?"]


async def test_the_target_runs_the_onnx_model(tmp_path: Path) -> None:
    target = TopicCheckTarget(OnnxSetFitTopicClassifier(write_topic_model(tmp_path)), 0.5)
    assert (await target({"question": "Explain photosynthesis"}))["off_topic"] is False


def test_an_on_topic_example_declined_is_a_false_rejection() -> None:
    assert false_rejections({"off_topic": True, "p_off_topic": 0.8}, ON)["score"] == 1
    assert false_rejections({"off_topic": False, "p_off_topic": 0.1}, ON)["score"] == 0
    assert false_rejections({"off_topic": True, "p_off_topic": 0.8}, OFF)["value"] == "n/a"


def test_an_off_topic_example_declined_is_caught() -> None:
    assert off_topic_caught({"off_topic": True, "p_off_topic": 0.8}, OFF)["score"] == 1
    assert off_topic_caught({"off_topic": False, "p_off_topic": 0.2}, OFF)["score"] == 0
    assert off_topic_caught({"off_topic": False, "p_off_topic": 0.2}, ON)["value"] == "n/a"


def test_a_failed_run_counts_against_both() -> None:
    assert false_rejections({}, ON)["score"] == 1
    assert off_topic_caught({}, OFF)["score"] == 0


def test_the_suite_runs_on_topic_check_and_is_skipped_without_a_model() -> None:
    assert SUITE.dataset == "topic_check" and SUITE.skip is not None
    reason = SUITE.skip()
    assert reason is None or "make topic-check-train" in reason
