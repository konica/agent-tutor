"""Hand-written eval datasets, versioned in LangSmith (PRD §10.3 item 6).

Each `datasets/<key>.yaml` is one LangSmith dataset (`name`) whose examples are grouped in splits (`smoke`, `full`). A
split's `version` tags the LangSmith dataset version that holds exactly its examples. The first run of a new version
replaces the split's examples and tags the result; later runs read the tagged version and refuse when the file no
longer matches it, so a version a run was gated on is never edited: give the split a new version instead.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import langsmith
import yaml
from langsmith.schemas import Example as LangSmithExample
from langsmith.utils import LangSmithNotFoundError

DATASETS = Path(__file__).parent / "datasets"


class DatasetError(Exception):
    """A dataset file is malformed, or no longer matches the LangSmith version it names."""


@dataclass(frozen=True)
class Example:
    inputs: dict[str, Any]
    outputs: dict[str, Any]


@dataclass(frozen=True)
class Split:
    name: str
    version: str  # a LangSmith dataset version tag
    examples: tuple[Example, ...]


@dataclass(frozen=True)
class Dataset:
    key: str  # the file's stem; suites name their dataset by it
    name: str  # the LangSmith dataset
    description: str
    splits: dict[str, Split]


def load_dataset(key: str, folder: Path = DATASETS) -> Dataset:
    path = folder / f"{key}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    splits: dict[str, Split] = {}
    for name, split in raw["splits"].items():
        if not split.get("version"):
            raise DatasetError(f"{path.name}: the {name} split has no version")
        examples = tuple(Example(dict(e["inputs"]), dict(e.get("outputs") or {})) for e in split.get("examples") or [])
        if not examples:
            raise DatasetError(f"{path.name}: the {name} split has no examples")
        splits[name] = Split(name, str(split["version"]), examples)
    return Dataset(key, raw["name"], raw.get("description", ""), splits)


def _canonical(examples: Iterable[Example]) -> list[str]:
    return sorted(json.dumps({"inputs": e.inputs, "outputs": e.outputs}, sort_keys=True) for e in examples)


def versioned_examples(client: langsmith.Client, dataset: Dataset, split: Split) -> list[LangSmithExample]:
    """The split's examples at its version, pushed and tagged first when LangSmith doesn't have that version yet."""
    if not client.has_dataset(dataset_name=dataset.name):
        client.create_dataset(dataset.name, description=dataset.description)
    try:
        client.read_dataset_version(dataset_name=dataset.name, tag=split.version)
    except LangSmithNotFoundError:
        _push(client, dataset, split)
    examples = list(client.list_examples(dataset_name=dataset.name, splits=[split.name], as_of=split.version))
    if _canonical(Example(e.inputs, e.outputs or {}) for e in examples) != _canonical(split.examples):
        raise DatasetError(
            f"{dataset.key}.yaml: the {split.name} split no longer matches LangSmith's {split.version}; "
            "give it a new version"
        )
    return examples


def _push(client: langsmith.Client, dataset: Dataset, split: Split) -> None:
    stale = [e.id for e in client.list_examples(dataset_name=dataset.name, splits=[split.name])]
    if stale:
        client.delete_examples(stale)
    client.create_examples(
        dataset_name=dataset.name,
        examples=[{"inputs": e.inputs, "outputs": e.outputs, "split": split.name} for e in split.examples],
    )
    # Tag the version that holds the new examples. Tagging needs an exact version time, so ask LangSmith for the
    # version at the latest change among them (the server's clock, not ours) instead of tagging that guess.
    pushed = list(client.list_examples(dataset_name=dataset.name, splits=[split.name]))
    latest = max(e.modified_at or e.created_at for e in pushed)
    version = client.read_dataset_version(dataset_name=dataset.name, as_of=latest)
    client.update_dataset_tag(dataset_name=dataset.name, as_of=version.as_of, tag=split.version)
