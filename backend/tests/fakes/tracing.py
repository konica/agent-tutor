"""Fakes for LangSmith tracing: a client that records payloads, and a RunTracing that records runs."""

from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from typing import Any

import langsmith

from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.run_tracing import RunTracing


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
