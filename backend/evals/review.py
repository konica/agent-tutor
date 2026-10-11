"""The human review gate before an item enters a dataset (PRD §10.3 item 6).

Generated candidates become runs in the dataset's candidates project (`<dataset>-candidates`) and are added to the
annotation queue of the same name. The queue's rubric asks the reviewer for `accepted`: 1 to accept, 0 to reject. Only
candidates whose latest `accepted` feedback is 1 come back as examples, for evals.publish to add to the next versions.
"""

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import langsmith
from langsmith.schemas import RunKey
from langsmith.utils import LangSmithNotFoundError

from evals.dataset import Dataset, Example

ACCEPTED = "accepted"
FEEDBACK_BATCH = 100  # run ids per list_feedback call
QUEUE_BATCH = 100  # runs per add to an annotation queue: LangSmith's limit
QUEUE_WAITS = (2, 4, 8, 15, 15, 15, 15, 15, 15, 15)  # seconds between tries of a queue add, about two minutes in all
RUBRIC = """\
Each item is a question proposed for the eval dataset, with the passages it was written from (outputs.evidence) and
the expected behavior (outputs.expected: covered = the learner's library answers it; not covered = the tutor must
decline). Accept (1) only when the question is clear, a learner could ask it, the evidence supports the expected
behavior, and for a covered question the passages answer it. Reject (0) anything you would need to edit; the next
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


def ensure_queue(client: langsmith.Client, dataset: Dataset) -> uuid.UUID:
    """The dataset's annotation queue, created with its `accepted` rubric item on first use."""
    name = candidates_name(dataset)
    for queue in client.list_annotation_queues(name=name):
        return queue.id
    if not list(client.list_feedback_configs(feedback_key=[ACCEPTED])):
        client.create_feedback_config(ACCEPTED, feedback_config={"type": "continuous", "min": 0, "max": 1})
    queue = client.create_annotation_queue(
        name=name,
        description=f"Generated candidates for the {dataset.name} dataset (backend/evals, make evals-generate)",
        rubric_instructions=RUBRIC,
        rubric_items=[
            {
                "feedback_key": ACCEPTED,
                "description": "1 = accept into the dataset, 0 = reject",
                "score_descriptions": {"0": "Reject", "1": "Accept"},
                "is_required": True,
            }
        ],
    )
    return queue.id


def _project_id(client: langsmith.Client, dataset: Dataset) -> uuid.UUID:
    """The candidates project's id, created on first use: each queue entry names its run's project."""
    name = candidates_name(dataset)
    if client.has_project(name):
        return client.read_project(project_name=name).id
    description = f"Generated candidates for the {dataset.name} dataset, reviewed in the annotation queue of this name"
    return client.create_project(name, description=description).id


def _queue(
    client: langsmith.Client, queue_id: uuid.UUID, runs: Sequence[RunKey], sleep: Callable[[float], None]
) -> None:
    """Add `runs` to the queue, retrying while LangSmith hasn't ingested them yet (it answers "not found")."""
    for wait in (*QUEUE_WAITS, None):
        try:
            client.add_runs_to_annotation_queue(queue_id, runs=runs)
            return
        except LangSmithNotFoundError:
            if wait is None:
                raise
            sleep(wait)


def submit(
    client: langsmith.Client,
    dataset: Dataset,
    candidates: Sequence[Candidate],
    metadata: Mapping[str, str],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[uuid.UUID]:
    """Record each candidate as a run in the candidates project and add them all to the queue."""
    queue_id = ensure_queue(client, dataset)
    project_id = _project_id(client, dataset)
    ids: list[uuid.UUID] = []
    keys: list[RunKey] = []
    start = datetime.now(UTC)
    for i, candidate in enumerate(candidates):
        # strictly increasing start times keep "oldest first" (publish's smoke order) well defined within a batch
        run_id, now = uuid.uuid4(), start + timedelta(microseconds=i)
        client.create_run(
            f"{dataset.key}-candidate",
            candidate.inputs,
            "chain",
            project_name=candidates_name(dataset),
            id=run_id,
            outputs={"expected": candidate.expected, "type": candidate.type, "evidence": list(candidate.evidence)},
            start_time=now,
            end_time=now,
            extra={"metadata": {"dataset": dataset.name, "type": candidate.type, **metadata}},
        )
        ids.append(run_id)
        keys.append({"run_id": run_id, "session_id": project_id, "start_time": now})
    client.flush()  # runs are sent in the background: they must exist before the queue can hold them
    for first in range(0, len(keys), QUEUE_BATCH):
        _queue(client, queue_id, keys[first : first + QUEUE_BATCH], sleep)
    return ids


def accepted(client: langsmith.Client, dataset: Dataset) -> list[Example]:
    """The candidates whose latest `accepted` feedback is 1, as examples, oldest candidate first."""
    try:
        runs = sorted(client.list_runs(project_name=candidates_name(dataset), is_root=True), key=lambda r: r.start_time)
    except LangSmithNotFoundError:
        return []  # nothing generated yet
    latest: dict[uuid.UUID, Any] = {}
    for start in range(0, len(runs), FEEDBACK_BATCH):
        batch = [r.id for r in runs[start : start + FEEDBACK_BATCH]]
        for feedback in client.list_feedback(run_ids=batch, feedback_key=[ACCEPTED]):
            seen = latest.get(feedback.run_id)
            if seen is None or feedback.modified_at > seen.modified_at:
                latest[feedback.run_id] = feedback
    return [
        Example(
            dict(run.inputs),
            dict(run.outputs["expected"]),
            {"type": run.outputs["type"], "candidate_run": str(run.id)},
        )
        for run in runs
        if run.id in latest and latest[run.id].score == 1
    ]
