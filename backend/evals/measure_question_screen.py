"""Measure the question screen per guardrail strength (#199, PRD D28): false-positive rate on the benign study
questions, catch rate on the injection taxonomy's attacks, latency, and cost against an average turn.

Usage: uv run --env-file ../.env --extra eval python -m evals.measure_question_screen \\
           [--guardrail ID:VERSION ...] [--strength LOW|MEDIUM|HIGH ...] [--concurrency 4]

`--guardrail` measures existing guardrails. `--strength` creates a temporary guardrail per strength with the
production definition, waits until it is READY, versions it, measures it, and deletes it (also on Ctrl-C). This calls
real Bedrock (ApplyGuardrail at $0.15 per 1,000 text units) with your AWS credentials. Prints one Markdown table row
per guardrail, then the benign questions it tripped on. Exits 1 when any call failed.
"""

import argparse
import asyncio
import math
import sys
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

import boto3

from evals.dataset import load_dataset
from smart_tutor.shared.adapters.aws.clients import bedrock_runtime_client
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.counter import NoCounter
from smart_tutor.tutoring.adapters.bedrock_question_screen import SCREEN_BOTO_CONFIG, BedrockQuestionScreen, Screening
from smart_tutor.tutoring.application import GUARD_MESSAGE
from smart_tutor.tutoring.ports.guard import Guard

STRENGTHS = ("LOW", "MEDIUM", "HIGH")
INPUT_PRICE = 0.33e-6  # dollars per input token of the answer model
OUTPUT_PRICE = 2.75e-6  # dollars per output token
UNIT_PRICE = 0.00015  # dollars per content-policy text unit (1,000 characters)
READY_ATTEMPTS = 30  # get_guardrail polls, two seconds apart: 60 s
Example = tuple[str, str, str]  # question, label, topic


@dataclass(frozen=True)
class Outcome:
    question: str
    label: str
    topic: str
    tripped: bool
    client_ms: float
    processing_ms: int | None
    text_units: int


@dataclass(frozen=True)
class Measurement:
    outcomes: Sequence[Outcome]
    failures: int


@dataclass(frozen=True)
class Summary:
    label: str
    false_positives: tuple[int, int]
    false_positive_questions: list[str]
    caught: tuple[int, int]
    caught_by_category: dict[str, tuple[int, int]]
    client_p50: float | None
    client_p95: float | None
    processing_p50: float | None
    processing_p95: float | None
    mean_text_units: float
    failures: int = 0
    turn_input_tokens: int = 0
    turn_output_tokens: int = 0

    @property
    def cost_per_question(self) -> float:
        return self.mean_text_units * UNIT_PRICE

    @property
    def share_of_turn(self) -> float:
        return cost_share(self.mean_text_units, self.turn_input_tokens, self.turn_output_tokens)


def percentile(values: Sequence[float], p: float) -> float | None:
    """Nearest rank: the smallest value with at least p percent of the values at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)), 1) - 1]


def turn_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * INPUT_PRICE + output_tokens * OUTPUT_PRICE


def cost_share(mean_text_units: float, input_tokens: int, output_tokens: int) -> float:
    """The screen's cost per question as a share of an average turn's model cost."""
    turn = turn_cost(input_tokens, output_tokens)
    return mean_text_units * UNIT_PRICE / turn if turn else math.nan


def question_screen_definition(strength: str, region: str) -> dict[str, Any]:
    """`create_guardrail` arguments of the production question screen at `strength`: the prompt-attack filter on
    input only, Standard tier through the US cross-region profile. The profile is named without an account id."""
    return {
        "name": f"smart-tutor-measure-{strength.lower()}-{uuid.uuid4().hex[:6]}",
        "description": f"Temporary question-screen measurement ({region}); deleted when the run ends.",
        "blockedInputMessaging": GUARD_MESSAGE,
        "blockedOutputsMessaging": GUARD_MESSAGE,
        "contentPolicyConfig": {
            "filtersConfig": [
                {
                    "type": "PROMPT_ATTACK",
                    "inputStrength": strength,
                    "outputStrength": "NONE",
                    "inputAction": "BLOCK",
                    "inputEnabled": True,
                    "outputEnabled": False,
                }
            ],
            "tierConfig": {"tierName": "STANDARD"},
        },
        "crossRegionConfig": {"guardrailProfileIdentifier": "us.guardrail.v1:0"},
    }


class Screener(Protocol):
    async def screen(self, question: str) -> Screening: ...


async def measure_guardrail(screen: Screener, examples: Sequence[Example], concurrency: int = 4) -> Measurement:
    """Every example through `screen`, at most `concurrency` in flight; a call that raised counts as a failure."""
    gate, outcomes, failures = asyncio.Semaphore(concurrency), [], 0

    async def one(example: Example) -> None:
        nonlocal failures
        question, label, topic = example
        async with gate:
            started = asyncio.get_running_loop().time()
            try:
                found = await screen.screen(question)
            except Exception as e:
                print(f"screen call failed: {type(e).__name__}", file=sys.stderr)
                failures += 1
                return
            elapsed = (asyncio.get_running_loop().time() - started) * 1000
        outcomes.append(Outcome(question, label, topic, found.tripped, elapsed, found.processing_ms, found.text_units))

    await asyncio.gather(*(one(e) for e in examples))
    return Measurement(outcomes, failures)


def summarize(label: str, measurement: Measurement, turn_input: int = 0, turn_output: int = 0) -> Summary:
    benign = [o for o in measurement.outcomes if o.label == "benign"]
    attacks = [o for o in measurement.outcomes if o.label == "attack"]
    by_category: defaultdict[str, list[bool]] = defaultdict(list)
    for o in attacks:
        by_category[o.topic].append(o.tripped)
    client = [o.client_ms for o in measurement.outcomes]
    processing = [float(o.processing_ms) for o in measurement.outcomes if o.processing_ms is not None]
    units = [o.text_units for o in measurement.outcomes]
    return Summary(
        label,
        (sum(o.tripped for o in benign), len(benign)),
        [o.question for o in benign if o.tripped],
        (sum(o.tripped for o in attacks), len(attacks)),
        {c: (sum(t), len(t)) for c, t in by_category.items()},
        percentile(client, 50),
        percentile(client, 95),
        percentile(processing, 50),
        percentile(processing, 95),
        sum(units) / len(units) if units else 0.0,
        measurement.failures,
        turn_input,
        turn_output,
    )


class Control(Protocol):
    def create_guardrail(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_guardrail(self, **kwargs: Any) -> dict[str, Any]: ...
    def create_guardrail_version(self, **kwargs: Any) -> dict[str, Any]: ...
    def delete_guardrail(self, **kwargs: Any) -> Any: ...


async def _await_ready(
    control: Control, guardrail_id: str, sleep: Callable[[float], Awaitable[None]], attempts: int
) -> None:
    for _ in range(attempts):
        status = (await asyncio.to_thread(control.get_guardrail, guardrailIdentifier=guardrail_id))["status"]
        if status == "READY":
            return
        if status == "FAILED":
            raise RuntimeError(f"guardrail {guardrail_id} is FAILED")
        await sleep(2)
    raise TimeoutError(f"guardrail {guardrail_id} did not become READY after {attempts} polls")


async def measure_strengths[T](
    control: Control,
    strengths: Sequence[str],
    region: str,
    measure: Callable[[str, str], Awaitable[T]],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ready_attempts: int = READY_ATTEMPTS,
) -> list[tuple[str, T]]:
    """For each strength: create a temporary guardrail, wait until READY, version it, `measure(id, version)`, and
    delete it, whatever happens (an error or Ctrl-C included)."""
    results: list[tuple[str, T]] = []
    for strength in strengths:
        created = await asyncio.to_thread(control.create_guardrail, **question_screen_definition(strength, region))
        guardrail_id = created["guardrailId"]
        try:
            await _await_ready(control, guardrail_id, sleep, ready_attempts)
            version = (await asyncio.to_thread(control.create_guardrail_version, guardrailIdentifier=guardrail_id))[
                "version"
            ]
            results.append((strength, await measure(guardrail_id, version)))
        finally:
            await asyncio.shield(asyncio.to_thread(control.delete_guardrail, guardrailIdentifier=guardrail_id))
    return results


HEADER = (
    "| Guardrail | False positives | Catch rate | Client p50/p95 ms | Guardrail p50/p95 ms | Text units | "
    "Cost/question | Share of a turn |\n|---|---|---|---|---|---|---|---|"
)


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def _ratio(done: tuple[int, int]) -> str:
    n, total = done
    return f"{n}/{total} ({n / total:.1%})" if total else "0/0"


def format_row(s: Summary) -> str:
    return (
        f"| {s.label} | {_ratio(s.false_positives)} | {s.caught[0]}/{s.caught[1]} "
        f"| {_ms(s.client_p50)}/{_ms(s.client_p95)} | {_ms(s.processing_p50)}/{_ms(s.processing_p95)} "
        f"| {s.mean_text_units:.2f} | ${s.cost_per_question:.6f} | {s.share_of_turn:.2%} |"
    )


def format_report(summaries: Sequence[Summary]) -> str:
    lines = [HEADER, *(format_row(s) for s in summaries)]
    for s in summaries:
        lines += ["", f"{s.label}: catch rate by category"]
        lines += [f"- {c}: {n}/{total}" for c, (n, total) in sorted(s.caught_by_category.items())]
        lines += ["", f"{s.label}: benign questions it tripped on ({len(s.false_positive_questions)})"]
        lines += [f"- {q}" for q in s.false_positive_questions] or ["- none"]
        if s.failures:
            lines += ["", f"{s.label}: {s.failures} calls failed"]
    return "\n".join(lines)


class _PassThrough(Guard):
    async def check_question(self, question: str) -> None:
        return None

    async def check_answer(self, text: str) -> None:
        return None


def _examples() -> list[Example]:
    return [
        (e.inputs["question"], e.outputs["label"], e.outputs["topic"]) for e in load_dataset("question_screen").examples
    ]


def _screen(settings: Settings, guardrail_id: str, version: str) -> BedrockQuestionScreen:
    return BedrockQuestionScreen(
        _PassThrough(),
        bedrock_runtime_client(settings, SCREEN_BOTO_CONFIG),
        guardrail_id,
        version,
        timeout=settings.question_guard_timeout_seconds,
        failures=NoCounter(),
    )


async def run(args: argparse.Namespace) -> int:
    settings, examples = Settings(), _examples()

    async def measure(label: str, guardrail_id: str, version: str) -> Summary:
        found = await measure_guardrail(_screen(settings, guardrail_id, version), examples, args.concurrency)
        return summarize(label, found, args.turn_input_tokens, args.turn_output_tokens)

    summaries: list[Summary] = []
    for spec in args.guardrail or []:
        guardrail_id, _, version = spec.partition(":")
        if not version:
            print(f"--guardrail takes ID:VERSION, got {spec!r}", file=sys.stderr)
            return 2
        summaries.append(await measure(spec, guardrail_id, version))
    if args.strength:
        control: Any = boto3.client("bedrock", region_name=settings.aws_region)
        for strength in args.strength:
            done = await measure_strengths(control, [strength], settings.aws_region, partial(measure, strength))
            summaries.extend(summary for _, summary in done)
    print(format_report(summaries))
    return 1 if any(s.failures for s in summaries) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guardrail", action="append", metavar="ID:VERSION", help="an existing guardrail to measure")
    parser.add_argument(
        "--strength", action="append", choices=STRENGTHS, help="create a temporary guardrail at this strength"
    )
    parser.add_argument(
        "--turn-input-tokens",
        type=int,
        default=2652,
        help="input tokens of an average ask turn (default 2652: mean of 16 local ask traces in Phoenix, 2026-10-13)",
    )
    parser.add_argument(
        "--turn-output-tokens",
        type=int,
        default=297,
        help="output tokens of an average ask turn (default 297: mean of the same 16 traces)",
    )
    parser.add_argument("--concurrency", type=int, default=4, help="screen calls in flight at once (default 4)")
    args = parser.parse_args(argv)
    if not (args.guardrail or args.strength):
        parser.error("name a guardrail (--guardrail ID:VERSION) or a strength (--strength LOW|MEDIUM|HIGH)")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
