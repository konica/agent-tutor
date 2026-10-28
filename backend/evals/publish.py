"""Publish the next versions of each dataset's splits (PRD §10.3 item 6).

Usage: uv run --env-file ../.env --extra eval python -m evals.publish [--dataset ask] [--dry-run]

`full` holds the dataset file's hand-written examples and every candidate a reviewer accepted in the annotation queue:
the newest `full` version's generated examples carry over (an example outlives its candidate trace), less any a
reviewer has since rejected, plus the newly accepted. `smoke` holds the hand-written examples and accepted candidates
taken in turn from each question type, oldest generated first, up to SMOKE_SIZE items in all. A split whose examples
changed gets the next version, the Langfuse dataset `<name>/<split>-vN` (evals.dataset); an unchanged one gets none. A
dataset whose file lists `splits: [full]` gets no `smoke` version.

Needs a key pair of the Langfuse project `smart-tutor-evals` (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY,
LANGFUSE_BASE_URL), which holds both the annotation queues and the datasets. A dry run reads them too.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence

from evals.dataset import (
    DATASETS,
    SPLITS,
    Dataset,
    DatasetError,
    Example,
    in_eval_share,
    load_dataset,
    newest_examples,
    publish_split,
    version_name,
)
from evals.langfuse_client import HINT, LangfuseClient, LangfuseError, SdkLangfuse
from evals.review import reviewed

SMOKE_SIZE = 30
# Question types of generated ask examples (PRD §10.3 items 1-2), in the order smoke takes them.
TYPES = ("factual", "conceptual", "multi_chunk", "multi_document", "unanswerable", "follow_up", "topic_switch", "drift")


def _key(example: Example) -> str:
    return json.dumps({"inputs": example.inputs, "outputs": example.outputs}, sort_keys=True)


def split_examples(
    dataset: Dataset, accepted: Sequence[Example], smoke_size: int = SMOKE_SIZE
) -> dict[str, list[Example]]:
    seen = {_key(e) for e in dataset.examples}
    new: list[Example] = []
    for example in accepted:
        if _key(example) not in seen:
            seen.add(_key(example))
            new.append(example)
    by_type: defaultdict[str, list[Example]] = defaultdict(list)
    for example in new:
        by_type[str(example.metadata.get("type"))].append(example)
    order = [t for t in TYPES if t in by_type] + sorted(set(by_type) - set(TYPES))
    smoke, turn = [e for e in dataset.examples if "smoke" in e.splits], 0
    while len(smoke) < smoke_size and any(turn < len(by_type[t]) for t in order):
        for kind in order:
            if turn < len(by_type[kind]) and len(smoke) < smoke_size:
                smoke.append(by_type[kind][turn])
        turn += 1
    full = [e for e in dataset.examples if "full" in e.splits]
    found = {"smoke": smoke, "full": [*full, *new]}
    return {split: found[split] for split in SPLITS if split in dataset.splits}


def oldest_first(examples: Iterable[Example]) -> list[Example]:
    """Generated examples in the order they were generated (those published without `generated_at` first)."""
    return sorted(examples, key=lambda e: (str(e.metadata.get("generated_at") or ""), str(e.metadata["candidate_run"])))


def generated_examples(client: LangfuseClient, dataset: Dataset) -> list[Example]:
    """The generated examples of the next versions, oldest first.

    The newest `full` version's generated examples are the base, so an example outlives its candidate trace (if one
    is deleted by hand): it leaves only when its trace still exists and is no longer accepted. Newly accepted
    candidates join it."""
    review = reviewed(client, dataset)
    examples = {
        str(e.metadata["candidate_run"]): e
        for e in newest_examples(client, dataset, "full")
        if "candidate_run" in e.metadata and str(e.metadata["candidate_run"]) not in review.withdrawn
    }
    examples.update((str(e.metadata["candidate_run"]), e) for e in review.accepted)
    return oldest_first(examples.values())


def _summary(examples: Sequence[Example]) -> str:
    # hand-written rows, gold labels included, carry no candidate_run
    counts = Counter(str(e.metadata.get("type")) if "candidate_run" in e.metadata else "hand-written" for e in examples)
    return ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))


def main(
    argv: Sequence[str] | None = None,
    *,
    client: LangfuseClient | None = None,
    load: Callable[[str], Dataset] = load_dataset,
    keys: Sequence[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", action="append", help="a datasets/<key>.yaml key (default: every dataset)")
    parser.add_argument("--dry-run", action="store_true", help="print each split's summary; publish nothing")
    args = parser.parse_args(argv)
    keys = args.dataset or keys or sorted(p.stem for p in DATASETS.glob("*.yaml"))
    try:
        client = client or SdkLangfuse()
        for key in keys:
            dataset = load(key)
            accepted = generated_examples(client, dataset)
            if dataset.eval_share is not None:  # the rest trains a model (evals.topic_check.train), never evaluates it
                accepted = [e for e in accepted if in_eval_share(str(e.inputs["question"]), dataset.eval_share)]
            splits = split_examples(dataset, accepted)
            for split, examples in splits.items():
                if args.dry_run:
                    print(f"{dataset.name} {split}: {len(examples)} examples ({_summary(examples)})")
                    continue
                tag = publish_split(client, dataset, split, examples)
                state = f"published {version_name(dataset, tag)}" if tag else "unchanged"
                print(f"{dataset.name} {split}: {state}, {len(examples)} examples ({_summary(examples)})")
            generated = {str(e.metadata.get("type")) for e in splits.get("smoke", ()) if "candidate_run" in e.metadata}
            # only the ask question types are expected in every smoke split (injection examples are typed by category)
            if generated & set(TYPES) and (missing := [t for t in TYPES if t not in generated]):
                print(f"{dataset.name} smoke: {', '.join(f'no accepted {t}' for t in missing)} (make evals-generate)")
    except DatasetError as e:
        print(f"Can't publish: {e}", file=sys.stderr)
        return 1
    except LangfuseError as e:
        print(f"Can't reach Langfuse: {e} ({HINT})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
