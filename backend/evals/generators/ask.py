"""Ask candidates from the seed corpus (PRD §10.3 items 1-2): factual, conceptual, multi-chunk, multi-document, and
unanswerable-but-on-topic questions, drift (a limited conversation whose last turn leaves the listed document),
follow-ups (a second question that names its subject only as "it"), and topic switches (an earlier question about
one held document, then a question about another).

Code picks the learner and the passages for each draft (seeded, so a seed plans the same drafts); the judge model
writes each question from its passages. A draft is covered when the learner's library answers it, and must be
declined otherwise; every candidate keeps the seed chunk ids it was written from.
"""

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from evals.chunks import SeedChunk
from evals.publish import TYPES
from evals.review import Candidate

LOG = logging.getLogger(__name__)
PROMPT = Path(__file__).parent / "prompts" / "ask_question.md"
MIN_CHARS = 400
MIN_LETTERS = 0.6  # share of letters and spaces: reference lists and tables fall below it
CLOSING_TAG = re.compile(r"</\s*passage\s*>", re.IGNORECASE)  # every spelling a model may read as closing a passage
INSTRUCTIONS = {
    "factual": "Ask for one specific fact the passage states (a number, a name, a result, a setting).",
    "conceptual": "Ask the learner's 'how' or 'why' question about the main idea of the passage.",
    "multi_chunk": "Ask a question that needs both passages to answer; each passage gives part of the answer.",
    "multi_document": "Ask a question that compares or connects the ideas of the two passages; it needs both.",
    "unanswerable": "Ask for one specific fact the passage states (a number, a name, a result, a setting).",
    "follow_up": (
        'Ask a follow-up about the passage\'s idea that names the method or paper only as "it", "this", or '
        '"they", as a learner continuing a conversation about it would.'
    ),
    "topic_switch": "Ask for one specific fact the passage states (a number, a name, a result, a setting).",
    "drift": "Ask a follow-up a learner might drift to, about the main idea of this passage.",
}

Write = Callable[[str, Sequence[SeedChunk]], Awaitable[str | None]]


@dataclass(frozen=True)
class Draft:
    type: str
    learner: str
    documents: tuple[str, ...] | None  # the conversation's limit (seed ids), or None for the whole library
    chunks: tuple[SeedChunk, ...]  # the passages the (last) question is written from
    history: tuple[SeedChunk, ...]  # one passage per earlier turn
    covered: bool
    sources: tuple[str, ...]  # seed ids that answer it


def usable(chunk: SeedChunk) -> bool:
    text = chunk.text
    return len(text) >= MIN_CHARS and sum(c.isalpha() or c.isspace() for c in text) / len(text) >= MIN_LETTERS


def plan_drafts(
    chunks: Mapping[str, Sequence[SeedChunk]],
    holdings: Mapping[str, Sequence[str]],
    per_type: int,
    rng: random.Random,
) -> list[Draft]:
    good = {seed: [c for c in found if usable(c)] for seed, found in chunks.items()}
    seeds = sorted(s for s, found in good.items() if found)
    learners = sorted(holdings)

    def held(learner: str) -> list[str]:
        return [s for s in holdings[learner] if s in seeds]

    def pick(seed: str, n: int = 1) -> tuple[SeedChunk, ...]:
        return tuple(sorted(rng.sample(good[seed], n), key=lambda c: c.seq))

    def draft(kind: str) -> Draft | None:
        if kind in ("factual", "conceptual"):
            owners = [u for u in learners if held(u)]
            if not owners:
                return None
            learner = rng.choice(owners)
            seed = rng.choice(held(learner))
            return Draft(kind, learner, None, pick(seed), (), True, (seed,))
        if kind == "multi_chunk":
            owners = [u for u in learners if any(len(good[s]) >= 2 for s in held(u))]
            if not owners:
                return None
            learner = rng.choice(owners)
            seed = rng.choice([s for s in held(learner) if len(good[s]) >= 2])
            return Draft(kind, learner, None, pick(seed, 2), (), True, (seed,))
        if kind == "multi_document":
            candidates = [u for u in learners if len(held(u)) >= 2]
            if not candidates:
                return None
            learner = rng.choice(candidates)
            a, b = sorted(rng.sample(held(learner), 2))
            return Draft(kind, learner, None, pick(a) + pick(b), (), True, (a, b))
        if kind == "unanswerable":
            owners = [u for u in learners if set(seeds) - set(held(u))]
            if not owners:
                return None
            learner = rng.choice(owners)
            seed = rng.choice(sorted(set(seeds) - set(held(learner))))
            return Draft(kind, learner, None, pick(seed), (), False, ())
        if kind == "follow_up":
            owners = [u for u in learners if any(len(good[s]) >= 2 for s in held(u))]
            if not owners:
                return None
            learner = rng.choice(owners)
            seed = rng.choice([s for s in held(learner) if len(good[s]) >= 2])
            earlier, last = rng.sample(good[seed], 2)
            return Draft(kind, learner, None, (last,), (earlier,), True, (seed,))
        if kind == "topic_switch":
            owners = [u for u in learners if len(held(u)) >= 2]
            if not owners:
                return None
            learner = rng.choice(owners)
            a, b = rng.sample(held(learner), 2)
            return Draft(kind, learner, None, pick(b), pick(a), True, (b,))
        # drift: limited to one held document; the last turn is written from another document
        owners = [u for u in learners if held(u) and len(seeds) >= 2]
        if not owners:
            return None
        learner = rng.choice(owners)
        limit = rng.choice(held(learner))
        other = rng.choice([s for s in seeds if s != limit])
        return Draft(kind, learner, (limit,), pick(other), pick(limit), False, ())

    drafts = []
    for kind in TYPES:
        for _ in range(per_type):
            if (made := draft(kind)) is not None:
                drafts.append(made)
    return drafts


async def write_candidates(drafts: Sequence[Draft], write: Write, concurrency: int = 4) -> list[Candidate]:
    """One candidate per draft whose every question the model wrote, in draft order."""
    gate = asyncio.Semaphore(concurrency)

    async def one(draft: Draft) -> Candidate | None:
        async with gate:
            try:
                history = [await write("factual", [chunk]) for chunk in draft.history]
                question = await write(draft.type, draft.chunks)
            except Exception as error:  # a parse error or throttling drops this draft, not the batch
                LOG.warning("Dropped a %s draft: %s: %s", draft.type, type(error).__name__, error)
                return None
        if question is None or None in history:
            return None
        inputs: dict[str, Any] = {
            "question": question,
            "learner": draft.learner,
            "documents": None if draft.documents is None else list(draft.documents),
        }
        if history:
            inputs["history"] = history
        return Candidate(
            inputs=inputs,
            expected={
                "covered": draft.covered,
                "sources": list(draft.sources),
                "chunks": [c.id for c in draft.chunks],
            },
            type=draft.type,
            evidence=tuple({"chunk": c.id, "text": c.text} for c in (*draft.history, *draft.chunks)),
        )

    return [c for c in await asyncio.gather(*(one(d) for d in drafts)) if c is not None]


class Question(BaseModel):
    """The question for the dataset."""

    question: str | None = Field(
        default=None, description="The question, or null when the passages can't support a good one."
    )


def question_writer(model: BaseChatModel) -> Write:
    """Has `model` (the judge role) write one question from quoted passages."""
    structured = model.with_structured_output(Question)
    template = PROMPT.read_text(encoding="utf-8")

    async def write(kind: str, passages: Sequence[SeedChunk]) -> str | None:
        # Passage text is untrusted: it must not be able to close its own tag.
        quoted = "\n\n".join(
            f'<passage id="{p.id}">\n{CLOSING_TAG.sub("&lt;/passage&gt;", p.text)}\n</passage>' for p in passages
        )
        reply = await structured.ainvoke(
            [SystemMessage(template.format(instruction=INSTRUCTIONS[kind])), HumanMessage(quoted)]
        )
        question = reply.question if isinstance(reply, Question) else None
        return (question.strip() or None) if question else None

    return write
