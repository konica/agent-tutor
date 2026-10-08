"""Run an evaluation split as a LangSmith experiment and check it against thresholds.yaml.

Usage: uv run --extra eval python -m evals.run --split smoke|full [--policy T,M,MM]

The subject-detection dataset is YAML in this repo; each run syncs it to LangSmith (examples matched by
`metadata.item_id`) and evaluates the chosen split against the policy the agent would load from SSM.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langsmith import Client, evaluate

from evals import gate
from evals.detection_dataset import DetectionItem, load_items
from evals.evaluators.subject_detection import subject_detection, summarize
from evals.targets import detection_target, parse_policy, seed_index, ssm_policy
from smart_tutor.shared.adapters.model_factory import ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.tutoring.domain.detection import DetectionPolicy

DATASET_NAMES = {"subject_detection": "smart-tutor-subject-detection"}


@dataclass(frozen=True)
class RemoteExample:
    id: str
    item_id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    splits: list[str]


@dataclass
class SyncPlan:
    create: list[DetectionItem] = field(default_factory=list)
    update: list[tuple[str, DetectionItem]] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)


def item_splits(item: DetectionItem) -> list[str]:
    return ["smoke", "full"] if item.smoke else ["full"]


def plan_sync(local: Sequence[DetectionItem], remote: Sequence[RemoteExample]) -> SyncPlan:
    """What makes LangSmith match the repo: missing items added, differing ones updated, removed ones deleted."""
    by_item = {r.item_id: r for r in remote}
    plan = SyncPlan()
    for item in local:
        existing = by_item.get(item.id)
        if existing is None:
            plan.create.append(item)
        elif (
            existing.inputs != item.inputs()
            or existing.outputs != item.reference_outputs()
            or sorted(existing.splits) != sorted(item_splits(item))
        ):
            plan.update.append((existing.id, item))
    local_ids = {i.id for i in local}
    plan.delete = [r.id for r in remote if r.item_id not in local_ids]
    return plan


def _metadata(item: DetectionItem) -> dict[str, Any]:
    return {"item_id": item.id, "kind": item.kind}


def sync_dataset(client: Client, name: str, items: Sequence[DetectionItem]) -> None:
    if not client.has_dataset(dataset_name=name):
        client.create_dataset(name, description="Subject detection: labeled first questions (PRD §10.1)")
    remote = [
        RemoteExample(
            id=str(e.id),
            item_id=str((e.metadata or {})["item_id"]),
            inputs=dict(e.inputs),
            outputs=dict(e.outputs or {}),
            splits=list((e.metadata or {}).get("dataset_split") or []),
        )
        for e in client.list_examples(dataset_name=name)
        if (e.metadata or {}).get("item_id")
    ]
    plan = plan_sync(items, remote)
    if plan.create:
        client.create_examples(
            dataset_name=name,
            examples=[
                {
                    "inputs": i.inputs(),
                    "outputs": i.reference_outputs(),
                    "metadata": _metadata(i),
                    "split": item_splits(i),
                }
                for i in plan.create
            ],
        )
    for example_id, i in plan.update:
        client.update_example(
            example_id,
            inputs=i.inputs(),
            outputs=i.reference_outputs(),
            metadata=_metadata(i),
            split=item_splits(i),
        )
    for example_id in plan.delete:
        client.delete_example(example_id)


def run_subject_detection(
    split: Literal["smoke", "full"], policy_override: DetectionPolicy | None, client: Client
) -> tuple[dict[str, float], str]:
    """Sync the dataset, run the split, and return mean scores and the experiment link (or name)."""
    settings = Settings()
    policy = policy_override or ssm_policy(settings)
    name = DATASET_NAMES["subject_detection"]
    sync_dataset(client, name, load_items("full"))
    target = detection_target(seed_index(settings), ModelFactory(settings).embedding(), policy)
    results = evaluate(
        target,
        data=client.list_examples(dataset_name=name, splits=[split]),
        evaluators=[subject_detection],
        experiment_prefix=f"subject-detection-{split}",
        metadata={
            "split": split,
            "detect_threshold": policy.detect_threshold,
            "detect_margin": policy.detect_margin,
            "multi_margin": policy.multi_margin,
        },
        max_concurrency=4,
        client=client,
    )
    rows = [
        {r.key: float(r.score) for r in row["evaluation_results"]["results"] if r.score is not None} for row in results
    ]
    return summarize(rows), results.url or results.experiment_name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["smoke", "full"], required=True)
    parser.add_argument("--policy", help="THRESHOLD,MARGIN,MULTI_MARGIN; overrides the SSM policy")
    args = parser.parse_args()
    override = parse_policy(args.policy) if args.policy else None
    scores, link = run_subject_detection(args.split, override, Client())
    goals = gate.targets(gate.load_thresholds(), "release_1", "subject_detection")
    for metric, (comparator, value) in goals.items():
        shown = f"{scores[metric]:.3f}" if metric in scores else "missing"
        print(f"{metric}: {shown} (target {comparator} {value:.2f})")
    print(f"experiment: {link}")
    failed = gate.failures(scores, goals)
    for message in failed:
        print(f"FAIL {message}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
