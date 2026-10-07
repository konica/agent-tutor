"""Load the detection thresholds from settings (SSM), never from code (PRD §9.2)."""

import math

from smart_tutor.shared.ports.parameter_store import ParameterStore
from smart_tutor.tutoring.domain.detection import DetectionPolicy


def _fraction(store: ParameterStore, name: str) -> float:
    value = store.get(name)
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not 0 <= number <= 1:  # also refuses nan and inf
        raise ValueError(f"SSM parameter {name} must be a number from 0 to 1, got {value!r}")
    return number


def load_detection_policy(
    store: ParameterStore, threshold_param: str, margin_param: str, multi_margin_param: str
) -> DetectionPolicy:
    return DetectionPolicy(
        detect_threshold=_fraction(store, threshold_param),
        detect_margin=_fraction(store, margin_param),
        multi_margin=_fraction(store, multi_margin_param),
    )
