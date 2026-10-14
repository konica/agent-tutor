"""Eval datasets, versioned in Langfuse (PRD §10.3 item 6, ADR 0023).

Each `datasets/<key>.yaml` is one eval dataset (`name`): its hand-written `examples`, which are in every version of
both splits (unless a top-level `splits` lists only some), and optional `pins` naming the version the runner must use
for a split. A split's versions are made only by publishing (evals.publish): when a split's examples differ from its
newest version, they become the next version, `<split>-v<N+1>`.

Each version is a Langfuse dataset of its own, `<name>/<split>-v<N>` (`smart-tutor-ask/smoke-v3`; Langfuse shows
`smart-tutor-ask/` as a folder). It is created, filled, and never written again, so a version a run was gated on is
never edited. Its metadata records its split and how many examples it holds: a version with fewer items (a publish
that stopped part-way) is incomplete, is never the newest, and its number is not reused. The runner uses a split's
newest version unless one is pinned.
"""

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from evals.langfuse_client import Item, LangfuseClient, StoredDataset

DATASETS = Path(__file__).parent / "datasets"
SPLITS = ("smoke", "full")


class DatasetError(Exception):
    """A dataset file is malformed, or names a version Langfuse doesn't have."""


@dataclass(frozen=True)
class Example:
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Dataset:
    key: str  # the file's stem; suites name their dataset by it
    name: str  # the Langfuse folder its versions are published in (`<name>/<split>-vN`)
    description: str
    examples: tuple[Example, ...]  # hand-written: in every version of every split
    pins: dict[str, str] = field(default_factory=dict)  # split -> the version tag the runner must use
    splits: tuple[str, ...] = SPLITS  # the splits the dataset is published to (`splits:` in its file)
    # a share of generated examples held out for evaluation; the rest train a model (topic_check)
    eval_share: float | None = None


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
    splits = tuple(str(split) for split in raw.get("splits") or SPLITS)
    if unknown := set(splits) - set(SPLITS):
        raise DatasetError(f"{path.name}: splits names unknown splits {sorted(unknown)} (splits: {', '.join(SPLITS)})")
    if outside := set(pins) - set(splits):
        raise DatasetError(f"{path.name}: pins name splits the dataset opts out of: {sorted(outside)}")
    share = raw.get("eval_share")
    if share is not None and not 0 < float(share) < 1:
        raise DatasetError(f"{path.name}: eval_share must be between 0 and 1, not {share}")
    return Dataset(
        key,
        raw["name"],
        raw.get("description", ""),
        examples,
        pins,
        splits,
        None if share is None else float(share),
    )


def _number(tag: str, split: str) -> int | None:
    match = re.fullmatch(rf"{re.escape(split)}-v(\d+)", tag)
    return int(match.group(1)) if match else None


def version_name(dataset: Dataset, tag: str) -> str:
    """The Langfuse dataset holding one version of a split."""
    return f"{dataset.name}/{tag}"


def _numbers(client: LangfuseClient, dataset: Dataset, split: str) -> list[int]:
    """The numbers of the split's versions in Langfuse, complete or not, highest first."""
    prefix = f"{dataset.name}/"
    found = (_number(name.removeprefix(prefix), split) for name in client.dataset_names() if name.startswith(prefix))
    return sorted((n for n in found if n is not None), reverse=True)


def _complete(stored: StoredDataset) -> bool:
    return stored.metadata.get("examples") == len(stored.items)


def _examples(stored: StoredDataset) -> list[Example]:
    return [Example(dict(i.input), dict(i.expected_output), dict(i.metadata)) for i in stored.items]


def _newest(client: LangfuseClient, dataset: Dataset, split: str) -> tuple[str, list[Example]] | None:
    """The split's highest complete version and its examples, or None."""
    for number in _numbers(client, dataset, split):
        tag = f"{split}-v{number}"
        stored = client.get_dataset(version_name(dataset, tag))
        if stored is not None and _complete(stored):
            return tag, _examples(stored)
    return None


def newest_version(client: LangfuseClient, dataset: Dataset, split: str) -> str | None:
    """The split's highest complete `<split>-vN` version, or None."""
    newest = _newest(client, dataset, split)
    return newest[0] if newest else None


def version_to_run(client: LangfuseClient, dataset: Dataset, split: str) -> str | None:
    """The pinned version of the split, else its newest; None when it has never been published."""
    pin = dataset.pins.get(split)
    if pin is None:
        return newest_version(client, dataset, split)
    stored = client.get_dataset(version_name(dataset, pin))
    if stored is None or not _complete(stored):
        found = "doesn't exist" if stored is None else "is incomplete"
        raise DatasetError(f"{dataset.key}.yaml pins {split} to {pin}, but {version_name(dataset, pin)} {found}")
    return pin


def examples_at(client: LangfuseClient, dataset: Dataset, version: str) -> list[Example]:
    """The examples of one version (a `<split>-vN` tag), with their metadata."""
    stored = client.get_dataset(version_name(dataset, version))
    if stored is None:
        raise DatasetError(f"{version_name(dataset, version)} doesn't exist")
    return _examples(stored)


def newest_examples(client: LangfuseClient, dataset: Dataset, split: str) -> list[Example]:
    """The examples of the split's newest version, with their metadata; none when it has never been published."""
    newest = _newest(client, dataset, split)
    return newest[1] if newest else []


def _canonical(examples: Iterable[Example]) -> list[str]:
    return sorted(json.dumps({"inputs": e.inputs, "outputs": e.outputs}, sort_keys=True) for e in examples)


def publish_split(client: LangfuseClient, dataset: Dataset, split: str, examples: Sequence[Example]) -> str | None:
    """Make `examples` the split's next version and return its tag; None when they equal the newest version."""
    newest = _newest(client, dataset, split)
    if newest is not None and _canonical(newest[1]) == _canonical(examples):
        return None
    # numbered past every version, an incomplete one included, so a name is never reused
    tag = f"{split}-v{max(_numbers(client, dataset, split), default=0) + 1}"
    name = version_name(dataset, tag)
    description = " ".join(filter(None, [dataset.description.strip(), f"({split} {tag}, made by make evals-publish)"]))
    client.create_dataset(name, description=description, metadata={"split": split, "examples": len(examples)})
    for example in examples:
        client.create_item(name, Item(example.inputs, example.outputs, example.metadata))
    return tag


def normalized(question: str) -> str:
    return " ".join(question.lower().split())


def in_eval_share(question: str, share: float) -> bool:
    """Whether a generated example is held out for evaluation: a stable hash of its normalized question, so it never
    moves between training and evaluation (spec 2026-10-13 §6.1)."""
    digest = hashlib.sha256(normalized(question).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < share
