"""Release-gate thresholds (`thresholds.yaml`): read targets, compare scores."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

THRESHOLDS_PATH = Path(__file__).resolve().parent / "thresholds.yaml"


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def targets(thresholds: Mapping[str, Any], release: str, suite: str) -> dict[str, tuple[str, float]]:
    """`{metric: ("min" | "max", value)}` for one suite of one release."""
    result: dict[str, tuple[str, float]] = {}
    for metric, entry in thresholds[release][suite].items():
        comparator = "min" if "min" in entry else "max"
        result[metric] = (comparator, float(entry[comparator]))
    return result


def failures(scores: Mapping[str, float], targets: Mapping[str, tuple[str, float]]) -> list[str]:
    """One message per missed or missing metric; empty when the gate passes."""
    found: list[str] = []
    for metric, (comparator, value) in targets.items():
        if metric not in scores:
            found.append(f"{metric} missing")
        elif comparator == "min" and scores[metric] < value:
            found.append(f"{metric} {scores[metric]:.2f} < min {value:.2f}")
        elif comparator == "max" and scores[metric] > value:
            found.append(f"{metric} {scores[metric]:.2f} > max {value:.2f}")
    return found
