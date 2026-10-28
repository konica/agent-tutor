"""The human review gate before an item enters a dataset (PRD §10.3 item 6), in Langfuse (ADR 0023 §5).

Generated candidates become traces named `<dataset>-candidates` in the `smart-tutor-evals` project (each a root span
sent over OpenTelemetry, since Langfuse v4 has no trace-create endpoint; evals.langfuse_client) and are added to the
annotation queue of the same name. The queue's description is the dataset's rubric, and its score config `accepted`
(BOOLEAN) asks the reviewer to accept (True) or reject (False). Only candidates whose latest `accepted` score is True
come back as examples, for evals.publish to add to the next versions; the other candidate traces come back as
withdrawn, so publishing drops an example a reviewer no longer accepts.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from evals.dataset import Dataset, Example
from evals.langfuse_client import LangfuseClient, Score, Trace

ACCEPTED = "accepted"
ENVIRONMENT = "local"  # make evals-generate runs on a developer's machine (ADR 0023 §5)
RUBRIC = """\
Each item is a question proposed for the eval dataset, with the passages it was written from (output.evidence) and
the expected behavior (output.expected: covered = the learner's library answers it; not covered = the tutor must
decline). Accept (True) only when the question is clear, a learner could ask it, the evidence supports the expected
behavior, and for a covered question the passages answer it. Reject (False) anything you would need to edit; the next
generation run proposes more.
"""


@dataclass(frozen=True)
class Candidate:
    inputs: dict[str, Any]
    expected: dict[str, Any]  # the example's reference outputs
    type: str  # the question type (generators/ask.py TYPES)
    evidence: tuple[dict[str, str], ...]  # {"chunk", "text"}: the passages the question was written from


def candidates_name(dataset: Dataset) -> str:
    return f"{dataset.name}-candidates"


def ensure_queue(client: LangfuseClient, dataset: Dataset, rubric: str = RUBRIC) -> str:
    """The dataset's annotation queue, created with the `accepted` score config on first use; `rubric` tells the
    reviewer what to accept (the ask rubric by default)."""
    name = candidates_name(dataset)
    if (queue_id := client.queue_id(name)) is not None:
        return queue_id
    config_id = client.score_config_id(ACCEPTED) or client.create_boolean_score_config(
        ACCEPTED, description="True = accept the candidate into its dataset, False = reject it"
    )
    description = f"Generated candidates for the {dataset.name} dataset (make evals-generate).\n\n{rubric}"
    return client.create_queue(name, description=description, score_config_id=config_id)


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="microseconds")


def submit(
    client: LangfuseClient,
    dataset: Dataset,
    candidates: Sequence[Candidate],
    metadata: Mapping[str, str],
    *,
    rubric: str = RUBRIC,
) -> list[str]:
    """Record each candidate as a trace and add them all to the dataset's queue; returns the trace ids."""
    queue_id = ensure_queue(client, dataset, rubric)
    start = datetime.now(UTC)
    traces: list[Trace] = []
    for i, candidate in enumerate(candidates):
        # strictly increasing times (Langfuse keeps milliseconds) keep "oldest first", publish's smoke order, well
        # defined within a batch
        at = start + timedelta(milliseconds=i)
        traces.append(
            Trace(
                uuid.uuid4().hex,
                candidates_name(dataset),
                dict(candidate.inputs),
                {"expected": candidate.expected, "type": candidate.type, "evidence": list(candidate.evidence)},
                {"dataset": dataset.name, "type": candidate.type, "generated_at": _iso(at), **metadata},
                at,
                ENVIRONMENT,
            )
        )
    client.create_traces(traces)
    for trace in traces:
        client.queue_trace(queue_id, trace.id)
    return [trace.id for trace in traces]


@dataclass(frozen=True)
class Reviewed:
    accepted: list[Example]  # candidates whose latest `accepted` score is True, oldest first
    withdrawn: set[str]  # trace ids of the other candidates that still exist: none of them may stay published


def _generated_at(trace: Trace) -> str:
    """When a candidate was generated, as UTC ISO 8601 with microseconds, sortable as text."""
    return str(trace.metadata.get("generated_at") or _iso(trace.timestamp))


def reviewed(client: LangfuseClient, dataset: Dataset) -> Reviewed:
    """The review state of the dataset's candidate traces that still exist (one deleted by hand is neither)."""
    traces = sorted(client.traces(candidates_name(dataset)), key=lambda t: (_generated_at(t), t.id))
    latest: dict[str, Score] = {}
    for score in client.boolean_scores(ACCEPTED):
        seen = latest.get(score.trace_id)
        if seen is None or score.updated_at >= seen.updated_at:
            latest[score.trace_id] = score
    accepted = [t for t in traces if t.id in latest and latest[t.id].value == 1]
    examples = [
        Example(
            dict(trace.input),
            dict(trace.output["expected"]),
            {"type": trace.output["type"], "candidate_run": trace.id, "generated_at": _generated_at(trace)},
        )
        for trace in accepted
    ]
    return Reviewed(examples, {t.id for t in traces} - {t.id for t in accepted})
