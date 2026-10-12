"""Eval datasets, versioned in LangSmith (PRD §10.3 item 6).

Each `datasets/<key>.yaml` is one LangSmith dataset (`name`): its hand-written `examples`, which are in every version of
both splits, and optional `pins` naming the version the runner must use for a split. A split's versions are made only
by publishing (evals.publish): when a split's examples differ from its newest version, they replace the split and the
result is tagged `<split>-v<N+1>`. Tags are never moved, so a version a run was gated on is never edited. The runner
uses a split's newest version unless one is pinned.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import langsmith
import yaml
from langsmith.schemas import Example as LangSmithExample
from langsmith.utils import LangSmithNotFoundError

DATASETS = Path(__file__).parent / "datasets"
SPLITS = ("smoke", "full")
SPLIT_KEY = "dataset_split"  # the example metadata key where LangSmith keeps an example's splits


class DatasetError(Exception):
    """A dataset file is malformed, or names a version LangSmith doesn't have."""


@dataclass(frozen=True)
class Example:
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Dataset:
    key: str  # the file's stem; suites name their dataset by it
    name: str  # the LangSmith dataset
    description: str
    examples: tuple[Example, ...]  # hand-written: in every version of every split
    pins: dict[str, str] = field(default_factory=dict)  # split -> the version tag the runner must use


def load_dataset(key: str, folder: Path = DATASETS) -> Dataset:
    path = folder / f"{key}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    examples = tuple(Example(dict(e["inputs"]), dict(e.get("outputs") or {})) for e in raw.get("examples") or [])
    if not examples:
        raise DatasetError(f"{path.name}: no examples")
    pins = {str(split): str(tag) for split, tag in (raw.get("pins") or {}).items()}
    if unknown := set(pins) - set(SPLITS):
        raise DatasetError(f"{path.name}: pins name unknown splits {sorted(unknown)} (splits: {', '.join(SPLITS)})")
    for split, tag in pins.items():
        if _number(tag, split) is None:
            raise DatasetError(f"{path.name}: pin {split}: {tag} is not a {split}-v<N> version")
    return Dataset(key, raw["name"], raw.get("description", ""), examples, pins)


def _number(tag: str, split: str) -> int | None:
    match = re.fullmatch(rf"{re.escape(split)}-v(\d+)", tag)
    return int(match.group(1)) if match else None


def newest_version(client: langsmith.Client, dataset_name: str, split: str) -> str | None:
    """The split's highest `<split>-vN` tag, or None."""
    numbers = [
        n
        for version in client.list_dataset_versions(dataset_name=dataset_name)
        for tag in version.tags or []
        if (n := _number(tag, split)) is not None
    ]
    return f"{split}-v{max(numbers)}" if numbers else None


def version_to_run(client: langsmith.Client, dataset: Dataset, split: str) -> str | None:
    """The pinned version of the split, else its newest; None when it has never been published."""
    if not client.has_dataset(dataset_name=dataset.name):
        return None
    pin = dataset.pins.get(split)
    if pin is None:
        return newest_version(client, dataset.name, split)
    try:
        client.read_dataset_version(dataset_name=dataset.name, tag=pin)
    except LangSmithNotFoundError:
        raise DatasetError(f"{dataset.key}.yaml pins {split} to {pin}, which {dataset.name} doesn't have") from None
    return pin


def examples_at(client: langsmith.Client, dataset: Dataset, split: str, version: str) -> list[LangSmithExample]:
    return list(client.list_examples(dataset_name=dataset.name, splits=[split], as_of=version))


def newest_examples(client: langsmith.Client, dataset: Dataset, split: str) -> list[Example]:
    """The examples of the split's newest version, with their metadata; none when it has never been published."""
    if not client.has_dataset(dataset_name=dataset.name):
        return []
    newest = newest_version(client, dataset.name, split)
    if newest is None:
        return []
    return [
        # LangSmith returns an example's splits in its metadata; publishing names the split on its own
        Example(dict(e.inputs), dict(e.outputs or {}), {k: v for k, v in (e.metadata or {}).items() if k != SPLIT_KEY})
        for e in examples_at(client, dataset, split, newest)
    ]


def _canonical(examples: Iterable[Example]) -> list[str]:
    return sorted(json.dumps({"inputs": e.inputs, "outputs": e.outputs}, sort_keys=True) for e in examples)


def publish_split(client: langsmith.Client, dataset: Dataset, split: str, examples: Sequence[Example]) -> str | None:
    """Make `examples` the split's next version and return its tag; None when they equal the newest version."""
    if not client.has_dataset(dataset_name=dataset.name):
        client.create_dataset(dataset.name, description=dataset.description)
    newest = newest_version(client, dataset.name, split)
    number = 0
    if newest is not None:
        current = (Example(e.inputs, e.outputs or {}) for e in examples_at(client, dataset, split, newest))
        if _canonical(current) == _canonical(examples):
            return None
        number = int(newest.rsplit("-v", 1)[1])
    tag = f"{split}-v{number + 1}"
    _push(client, dataset, split, examples, tag)
    return tag


def _push(client: langsmith.Client, dataset: Dataset, split: str, examples: Sequence[Example], tag: str) -> None:
    stale = [e.id for e in client.list_examples(dataset_name=dataset.name, splits=[split])]
    if stale:
        client.delete_examples(stale)
    client.create_examples(
        dataset_name=dataset.name,
        examples=[
            {"inputs": e.inputs, "outputs": e.outputs, "metadata": e.metadata or None, "split": split} for e in examples
        ],
    )
    # Tag the version that holds the new examples. Tagging needs an exact version time, so ask LangSmith for the
    # version at the latest change among them (the server's clock, not ours) instead of tagging that guess.
    pushed = list(client.list_examples(dataset_name=dataset.name, splits=[split]))
    latest = max(e.modified_at or e.created_at for e in pushed)
    version = client.read_dataset_version(dataset_name=dataset.name, as_of=latest)
    client.update_dataset_tag(dataset_name=dataset.name, as_of=version.as_of, tag=tag)
