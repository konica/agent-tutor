"""Building the topic check from settings (spec 2026-10-13 §5.4)."""

from pathlib import Path

import numpy as np
import pytest

from fakes import write_topic_model
from smart_tutor.apps.agent.topic import topic_classifier, topic_threshold
from smart_tutor.shared.config import Settings, TopicCheckConfig
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier


def test_the_check_is_off_by_default() -> None:
    config = Settings(_env_file=None).topic_check
    assert config.provider == "off" and config.model_dir == "models/topic_check" and config.timeout_ms == 250
    assert topic_classifier(config) is None


def test_settings_read_the_topic_check_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_TUTOR_TOPIC_CHECK__PROVIDER", "setfit")
    monkeypatch.setenv("SMART_TUTOR_TOPIC_CHECK__MODEL_DIR", "/m")
    monkeypatch.setenv("SMART_TUTOR_TOPIC_CHECK__THRESHOLD", "0.8")
    config = Settings(_env_file=None).topic_check
    assert (config.provider, config.model_dir, config.threshold) == ("setfit", "/m", 0.8)


def test_setfit_loads_the_model_and_its_threshold(tmp_path: Path) -> None:
    write_topic_model(tmp_path, threshold=0.7)
    config = TopicCheckConfig(provider="setfit", model_dir=str(tmp_path))
    classifier = topic_classifier(config)
    assert isinstance(classifier, OnnxSetFitTopicClassifier)
    assert topic_threshold(config, classifier) == 0.7


def test_a_configured_threshold_overrides_the_models(tmp_path: Path) -> None:
    write_topic_model(tmp_path, threshold=0.7)
    config = TopicCheckConfig(provider="setfit", model_dir=str(tmp_path), threshold=0.9)
    assert topic_threshold(config, topic_classifier(config)) == 0.9


def test_no_classifier_never_declines() -> None:
    assert topic_threshold(TopicCheckConfig(), None) == 1.0


def test_setfit_without_a_model_stops_startup(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        topic_classifier(TopicCheckConfig(provider="setfit", model_dir=str(tmp_path / "missing")))


def test_a_model_whose_parts_do_not_fit_stops_startup(tmp_path: Path) -> None:
    write_topic_model(tmp_path)
    np.savez(tmp_path / "head.npz", coef=np.zeros((1, 3), np.float32), intercept=np.zeros(1, np.float32))
    with pytest.raises(Exception):  # noqa: B017 - the error type is numpy's or onnxruntime's, not ours
        topic_classifier(TopicCheckConfig(provider="setfit", model_dir=str(tmp_path)))


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ValueError):
        TopicCheckConfig(provider="jev")  # type: ignore[arg-type]
