"""Generate dataset candidates and send them to the annotation queue (PRD §10.3 items 1, 2, 5, 6).

Usage: uv run --env-file ../.env --extra eval --extra ingest python -m evals.generate
    ask|injection|topic_check [--per-type 6] [--seed N]

ask: downloads the seed PDFs if needed, cuts them into the worker's chunks, plans --per-type drafts of each question
type for the eval learners, and has the judge model (never the tutor's) write each question. injection: has the judge
model rewrite each prompt seed of adversarial/taxonomy.yaml into --per-type variants of its category. Either way the
candidates go to the dataset's annotation queue in Langfuse; nothing enters a dataset until a reviewer accepts it
(make evals-publish). topic_check: has the judge model write `--per-type` learner messages of each kind
(generators/topic_check.py). Needs your AWS profile (the judge on Bedrock) and a key pair of the Langfuse project
smart-tutor-evals (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL).
"""

import argparse
import asyncio
import random
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from evals.chunks import SeedChunk, seed_chunks
from evals.corpus import download, load_manifest
from evals.dataset import load_dataset
from evals.generators import injection, topic_check
from evals.generators.ask import Write, plan_drafts, question_writer, write_candidates
from evals.langfuse_client import HINT, LangfuseClient, LangfuseError, SdkLangfuse
from evals.learners import LEARNERS, load_learners
from evals.review import RUBRIC, Candidate, candidates_name, submit


def main(
    argv: Sequence[str] | None = None,
    *,
    client: LangfuseClient | None = None,
    chunks: Mapping[str, Sequence[SeedChunk]] | None = None,
    holdings: Mapping[str, Sequence[str]] | None = None,
    write: Write | None = None,
    vary: injection.Vary | None = None,
    write_topic: topic_check.Write | None = None,
    model_id: str | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "dataset", choices=["ask", "injection", "topic_check"], help="the datasets/<key>.yaml the candidates are for"
    )
    parser.add_argument(
        "--per-type", type=int, default=6, help="drafts per question type, or variants per injection seed (default 6)"
    )
    parser.add_argument("--seed", type=int, default=None, help="plan the same ask drafts again (default: random)")
    args = parser.parse_args(argv)
    try:
        client = client or SdkLangfuse()  # before the judge runs: missing keys stop it before it costs anything
    except LangfuseError as e:
        print(f"Can't reach Langfuse: {e} ({HINT})", file=sys.stderr)
        return 1
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**31)
    writer = {"ask": write, "injection": vary, "topic_check": write_topic}[args.dataset]
    if writer is None or model_id is None:
        from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
        from smart_tutor.shared.config import Settings

        settings = Settings()
        judge = ModelFactory(settings).chat(ChatRole.JUDGE)
        write = write or question_writer(judge)
        vary = vary or injection.variant_writer(judge)
        write_topic = write_topic or topic_check.message_writer(judge)
        model_id = model_id or settings.models.judge.model_id
    dataset = load_dataset(args.dataset)
    candidates: list[Candidate]
    if args.dataset == "injection":
        assert vary is not None
        rubric, planned = injection.RUBRIC, "seeds"
        candidates = asyncio.run(injection.write_candidates(injection.load_taxonomy(), args.per_type, vary))
        batch = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        dropped = ""
    elif args.dataset == "topic_check":
        assert write_topic is not None
        rubric, planned = topic_check.RUBRIC, "kinds"
        candidates = asyncio.run(topic_check.write_candidates(args.per_type, write_topic))
        batch = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        dropped = ""
    else:
        assert write is not None
        if chunks is None or holdings is None:
            seeds = load_manifest()
            # adversarial and control documents belong to the injection eval: their chunks must not seed Q&A,
            # unanswerable, or drift candidates (#196)
            chunks = seed_chunks(download(s for s in seeds.values() if not s.injection_eval))
            holdings = {learner.username: learner.documents for learner in load_learners(LEARNERS, seeds)}
        rubric, planned = RUBRIC, "drafts"
        drafts = plan_drafts(chunks, holdings, args.per_type, random.Random(seed))
        candidates = asyncio.run(write_candidates(drafts, write))
        batch = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-seed{seed}"
        dropped = f" ({len(drafts) - len(candidates)} drafts dropped)"
    if not candidates:
        print(f"No candidate was written from the {planned}; nothing was queued.", file=sys.stderr)
        return 1
    try:
        submit(
            client,
            dataset,
            candidates,
            {"generator_model": model_id, "batch": batch},
            rubric=rubric,
        )
    except LangfuseError as e:
        print(f"Can't reach Langfuse: {e} ({HINT})", file=sys.stderr)
        return 1
    print(
        f"Queued {len(candidates)} candidates{dropped} in the {candidates_name(dataset)} annotation queue, "
        f"batch {batch}. Review them in Langfuse, then make evals-publish."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
