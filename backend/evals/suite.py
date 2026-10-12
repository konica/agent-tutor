"""Eval suites (PRD §10.1). A suite is an evaluator module in `evaluators/` with a `SUITE`: the dataset it runs on
(`datasets/<dataset>.yaml`), how that dataset's examples are run (`target`, built once per run), and its evaluators,
each returning {"key": <thresholds.yaml metric>, "score", "comment"}. The runner discovers the suites; suites on one
dataset share one experiment, so the agent answers each example once.
"""

import importlib
import pkgutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from evals.targets import Target

Evaluator = Callable[..., Any]  # takes any of inputs, outputs, reference_outputs; sync or async
NOT_APPLICABLE = "n/a"  # an evaluator's `value` for an example its metric doesn't cover; the runner leaves it out


def not_applicable(key: str, why: str) -> dict[str, Any]:
    return {"key": key, "score": None, "value": NOT_APPLICABLE, "comment": why}


@dataclass(frozen=True)
class Suite:
    dataset: str
    target: Callable[[], Target]
    evaluators: tuple[Evaluator, ...]


@dataclass(frozen=True)
class DatasetSuites:
    """Every suite on one dataset: one experiment."""

    dataset: str
    target: Callable[[], Target]
    evaluators: tuple[Evaluator, ...]


def discover(package: ModuleType | None = None) -> list[Suite]:
    if package is None:
        package = importlib.import_module("evals.evaluators")
    suites: list[Suite] = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        suite = getattr(importlib.import_module(f"{package.__name__}.{info.name}"), "SUITE", None)
        if isinstance(suite, Suite):
            suites.append(suite)
    return suites


def by_dataset(suites: Sequence[Suite]) -> list[DatasetSuites]:
    groups: dict[str, DatasetSuites] = {}
    for suite in suites:
        group = groups.get(suite.dataset)
        if group is None:
            groups[suite.dataset] = DatasetSuites(suite.dataset, suite.target, suite.evaluators)
        elif group.target is not suite.target:
            raise ValueError(f"suites on the {suite.dataset} dataset name different targets")
        else:
            groups[suite.dataset] = DatasetSuites(suite.dataset, group.target, group.evaluators + suite.evaluators)
    return list(groups.values())
