"""The agent's topic check from settings (spec 2026-10-13 §5.4). Shared by the server and the eval targets."""

from pathlib import Path

from smart_tutor.shared.config import TopicCheckConfig
from smart_tutor.tutoring.application import TopicClassifier


def topic_classifier(config: TopicCheckConfig) -> TopicClassifier | None:
    """The configured classifier, or None when the check is off. A missing or broken model raises: startup stops."""
    if config.provider == "off":
        return None
    # Imported here so the agent doesn't load onnxruntime while the check is off.
    from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier

    classifier = OnnxSetFitTopicClassifier(Path(config.model_dir))
    # Score one text now: a model whose parts don't fit (a head of the wrong width, say) stops startup here rather
    # than failing open on every question.
    classifier.p_off_topic(["warm-up"])
    return classifier


def topic_threshold(config: TopicCheckConfig, classifier: TopicClassifier | None) -> float:
    """The configured threshold, else the model's own; 1.0 (never off-topic) when there is no classifier."""
    if config.threshold is not None:
        return config.threshold
    return classifier.default_threshold if classifier is not None else 1.0
