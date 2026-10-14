"""The LangSmith client calls the review queue makes (evals.review, until it moves to Langfuse with #319), in memory:
runs, feedback, projects, and annotation queues."""

import itertools
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from langsmith.utils import LangSmithError, LangSmithNotFoundError, LangSmithUserError

START = datetime(2026, 10, 11, tzinfo=UTC)


@dataclass(frozen=True)
class FakeRun:
    id: uuid.UUID
    name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None
    run_type: str
    project_name: str
    start_time: datetime
    extra: dict[str, Any] | None


@dataclass(frozen=True)
class FakeFeedback:
    id: uuid.UUID
    run_id: uuid.UUID
    key: str
    score: float | None
    modified_at: datetime


@dataclass(frozen=True)
class FakeProject:
    id: uuid.UUID
    name: str
    description: str | None


@dataclass
class FakeQueue:
    id: uuid.UUID
    name: str
    description: str | None
    rubric_instructions: str | None
    rubric_items: list[dict[str, Any]]
    run_ids: list[uuid.UUID] = field(default_factory=list)


class FakeLangSmith:
    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, FakeRun] = {}
        self.feedback: list[FakeFeedback] = []
        self.feedback_configs: dict[str, dict[str, Any]] = {}
        self.queues: dict[uuid.UUID, FakeQueue] = {}
        self.projects: dict[str, FakeProject] = {}
        self.queue_adds: list[list[dict[str, Any]]] = []  # the runs of each successful add to a queue
        self.ingestion_lag = 0  # queue adds that fail with "not found" before new runs become visible
        self.flushed = 0
        self._clock = itertools.count(1)

    def _now(self) -> datetime:
        return START + timedelta(seconds=next(self._clock))

    def has_project(self, project_name: str) -> bool:
        return project_name in self.projects

    def create_project(self, project_name: str, *, description: str | None = None) -> FakeProject:
        if project_name in self.projects:
            raise LangSmithError(f"project {project_name} exists")
        project = self.projects[project_name] = FakeProject(uuid.uuid4(), project_name, description)
        return project

    def read_project(self, *, project_name: str) -> FakeProject:
        if project_name not in self.projects:
            raise LangSmithNotFoundError(f"Project {project_name} not found")
        return self.projects[project_name]

    def create_run(self, name: str, inputs: dict[str, Any], run_type: str, *, project_name: str, **kwargs: Any) -> None:
        if project_name not in self.projects:  # as LangSmith: tracing to a new project creates it
            self.projects[project_name] = FakeProject(uuid.uuid4(), project_name, None)
        run_id = kwargs["id"]
        self.runs[run_id] = FakeRun(
            run_id,
            name,
            dict(inputs),
            kwargs.get("outputs"),
            run_type,
            project_name,
            kwargs.get("start_time") or self._now(),
            kwargs.get("extra"),
        )

    def flush(self) -> None:
        self.flushed += 1

    def list_runs(self, *, project_name: str, is_root: bool | None = None) -> Iterator[FakeRun]:
        self.read_project(project_name=project_name)
        return iter([r for r in self.runs.values() if r.project_name == project_name])

    def create_feedback(self, run_id: uuid.UUID, key: str, *, score: float | None = None) -> None:
        self.feedback.append(FakeFeedback(uuid.uuid4(), run_id, key, score, self._now()))

    def list_feedback(
        self, *, run_ids: Sequence[uuid.UUID], feedback_key: Sequence[str] | None = None
    ) -> Iterator[FakeFeedback]:
        if len(run_ids) > 100:  # keep callers batching: real query strings have a length limit
            raise LangSmithError("too many run ids")
        return iter(f for f in self.feedback if f.run_id in run_ids and (feedback_key is None or f.key in feedback_key))

    def list_feedback_configs(self, *, feedback_key: Sequence[str]) -> Iterator[dict[str, Any]]:
        return iter({"feedback_key": k, **self.feedback_configs[k]} for k in feedback_key if k in self.feedback_configs)

    def create_feedback_config(self, feedback_key: str, *, feedback_config: dict[str, Any]) -> None:
        if feedback_key in self.feedback_configs:
            raise LangSmithError(f"{feedback_key} exists")
        self.feedback_configs[feedback_key] = dict(feedback_config)

    def list_annotation_queues(self, *, name: str) -> Iterator[FakeQueue]:
        return iter(q for q in self.queues.values() if q.name == name)

    def create_annotation_queue(
        self,
        *,
        name: str,
        description: str | None = None,
        rubric_instructions: str | None = None,
        rubric_items: list[dict[str, Any]] | None = None,
    ) -> FakeQueue:
        for item in rubric_items or []:
            if item["feedback_key"] not in self.feedback_configs:  # as LangSmith: the config must exist first
                raise LangSmithError(f"no feedback config {item['feedback_key']}")
        queue = FakeQueue(uuid.uuid4(), name, description, rubric_instructions, list(rubric_items or []))
        self.queues[queue.id] = queue
        return queue

    def add_runs_to_annotation_queue(
        self,
        queue_id: uuid.UUID,
        *,
        runs: Sequence[dict[str, Any]] | None = None,
        run_ids: Sequence[uuid.UUID] | None = None,
    ) -> None:
        if run_ids is not None or runs is None:  # deprecated in SDK 0.14, and unusable on SmithDB workspaces
            raise LangSmithUserError("pass runs (RunKeys), not run_ids")
        if len(runs) > 100:  # as LangSmith: at most 100 runs per add
            raise LangSmithError("at most 100 runs per add")
        if self.ingestion_lag:  # runs sent moments ago aren't ingested yet
            self.ingestion_lag -= 1
            raise LangSmithNotFoundError(f"404 Not Found for /annotation-queues/{queue_id}/runs/by-key")
        for key in runs:
            run = self.runs.get(uuid.UUID(str(key["run_id"])))
            if run is None or (str(key["session_id"]), key["start_time"]) != (
                str(self.projects[run.project_name].id),
                run.start_time,
            ):
                raise LangSmithNotFoundError(f"no run with key {key}")
        self.queue_adds.append(list(runs))
        self.queues[queue_id].run_ids.extend(uuid.UUID(str(key["run_id"])) for key in runs)
