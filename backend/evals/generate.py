"""Generate dataset candidates from the seed corpus and send them to the annotation queue (PRD §10.3 items 1, 2, 6).

Usage: uv run --env-file ../.env --extra eval --extra ingest python -m evals.generate ask [--per-type 6] [--seed N]

Downloads the seed PDFs if needed, cuts them into the worker's chunks, plans --per-type drafts of each question type
for the eval learners, has the judge model (never the tutor's) write each question, and adds the candidates to the
dataset's annotation queue in LangSmith. Nothing enters a dataset until a reviewer accepts it (make evals-publish).
Needs your AWS profile (the judge on Bedrock) and LANGSMITH_API_KEY.
"""

import argparse
import asyncio
import random
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import langsmith
from langsmith.utils import LangSmithError

from evals.chunks import SeedChunk, seed_chunks
from evals.corpus import download, load_manifest
from evals.dataset import load_dataset
from evals.generators.ask import Write, plan_drafts, question_writer, write_candidates
from evals.learners import LEARNERS, load_learners
from evals.review import candidates_name, submit


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Any = None,
    chunks: Mapping[str, Sequence[SeedChunk]] | None = None,
    holdings: Mapping[str, Sequence[str]] | None = None,
    write: Write | None = None,
    model_id: str | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", choices=["ask"], help="the datasets/<key>.yaml the candidates are for")
    parser.add_argument("--per-type", type=int, default=6, help="drafts per question type (default 6)")
    parser.add_argument("--seed", type=int, default=None, help="plan the same drafts again (default: random)")
    args = parser.parse_args(argv)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**31)
    if chunks is None or holdings is None:
        seeds = load_manifest()
        chunks = seed_chunks(download(seeds.values()))
        holdings = {learner.username: learner.documents for learner in load_learners(LEARNERS, seeds)}
    if write is None or model_id is None:
        from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
        from smart_tutor.shared.config import Settings

        settings = Settings()
        write = question_writer(ModelFactory(settings).chat(ChatRole.JUDGE))
        model_id = settings.models.judge.model_id
    dataset = load_dataset(args.dataset)
    drafts = plan_drafts(chunks, holdings, args.per_type, random.Random(seed))
    candidates = asyncio.run(write_candidates(drafts, write))
    if not candidates:
        print(f"No candidate was written from {len(drafts)} drafts; nothing was queued.", file=sys.stderr)
        return 1
    batch = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-seed{seed}"
    try:
        submit(client or langsmith.Client(), dataset, candidates, {"generator_model": model_id, "batch": batch})
    except LangSmithError as e:
        print(f"Can't reach LangSmith: {e} (check LANGSMITH_API_KEY)", file=sys.stderr)
        return 1
    print(
        f"Queued {len(candidates)} candidates ({len(drafts) - len(candidates)} drafts dropped) in the "
        f"{candidates_name(dataset)} annotation queue, batch {batch}. "
        "Review them in LangSmith, then make evals-publish."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
