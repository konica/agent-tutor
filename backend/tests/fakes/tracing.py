"""Fakes for LangSmith tracing: a client that records payloads, and a RunTracing that records runs."""

import uuid
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import Executor, Future
from contextlib import AbstractContextManager, nullcontext
from types import SimpleNamespace
from typing import Any, TypeVar

import langsmith

from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.run_tracing import RunTracing

T = TypeVar("T")


class RecordingClient(langsmith.Client):
    """LangSmith client that records create/update payloads instead of sending them."""

    def __init__(self) -> None:
        super().__init__(api_key="test-not-a-key", api_url="http://127.0.0.1:9", auto_batch_tracing=False)
        self.payloads: list[dict[str, Any]] = []

    def create_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "create", **kwargs})

    def update_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "update", "run_id": str(args[0]) if args else None, **kwargs})


class FakeRunTracing(RunTracing):
    """Records each run's name, learner, and metadata."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, UserId, dict[str, str]]] = []

    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]:
        self.runs.append((name, user_id, dict(metadata)))
        return nullcontext()


class FeedbackClient(langsmith.Client):
    """LangSmith client that keeps feedback in memory and records each call's arguments; never reaches the network.
    `fail` makes every call raise, as an outage would."""

    def __init__(self, fail: Exception | None = None) -> None:
        super().__init__(api_key="test-not-a-key", api_url="http://127.0.0.1:9", auto_batch_tracing=False)
        self.project_id = uuid.uuid4()
        self.feedback: dict[uuid.UUID, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail = fail

    def _call(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if self._fail is not None:
            raise self._fail

    def read_project(self, **kwargs: Any) -> Any:
        self._call("read_project", kwargs)
        return SimpleNamespace(id=self.project_id)

    def list_feedback(self, **kwargs: Any) -> Iterator[Any]:
        self._call("list_feedback", kwargs)
        runs = {str(r) for r in kwargs.get("run_ids") or []}
        keys = set(kwargs.get("feedback_key") or [])
        return iter(
            [
                SimpleNamespace(id=i, **f)
                for i, f in self.feedback.items()
                if str(f["run_id"]) in runs and f["key"] in keys
            ]
        )

    def delete_feedback(self, feedback_id: Any) -> None:
        self._call("delete_feedback", {"feedback_id": feedback_id})
        del self.feedback[feedback_id]

    def create_feedback(self, run_id: Any = None, key: str = "unnamed", **kwargs: Any) -> Any:
        self._call("create_feedback", {"run_id": run_id, "key": key, **kwargs})
        feedback_id = uuid.uuid4()
        self.feedback[feedback_id] = {"run_id": run_id, "key": key, **kwargs}
        return SimpleNamespace(id=feedback_id)


class InlineExecutor(Executor):
    """Runs each task at once on the caller's thread, so a test sees its effect when `submit` returns."""

    def submit(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        future: Future[T] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as e:
            future.set_exception(e)
        return future
