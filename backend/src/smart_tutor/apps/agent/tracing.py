"""Each ask is one LangSmith trace named `ask` (PRD §10.4). Its metadata says where and with which models it ran,
for which thread, whether the search was limited to the conversation's documents, and, once done, the decline code
and how many chunks the model was given. The learner appears only as a keyed hash; the token stays in runtime context
(ADR 0007)."""

import logging
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import langsmith
from langsmith.run_trees import RunTree

from smart_tutor.shared.adapters.tracing import LearnerHasher, never_raising
from smart_tutor.shared.domain.ids import UserId

NO_DECLINE = "none"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AskRun:
    run_id: uuid.UUID  # the trace's root run; the API keeps it with the turn
    thread_id: str | None
    user_id: UserId  # hashed before it reaches the trace
    question: str
    document_ids: list[str] | None


class AskTrace:
    def __init__(self, run: RunTree | None) -> None:
        self._run = run  # None: the trace didn't start, so there is nothing to end

    def finish(self, answer: str, decline: str | None, chunks: int) -> None:
        """What the run ended with: a decline gives the model no chunks."""
        self._end(
            outputs={"answer": answer, "decline": decline},
            metadata={"decline": decline or NO_DECLINE, "chunks": 0 if decline else chunks},
        )

    def fail(self, code: str) -> None:
        """The run ended with an error event; the learner saw `code`."""
        self._end(error=code, metadata={"decline": NO_DECLINE, "chunks": 0})

    def _end(self, **fields: Any) -> None:
        if self._run is None:
            return
        try:
            self._run.end(**fields)
        except Exception:  # tracing never fails the ask (#229)
            logger.warning("could not end the ask trace", exc_info=True)


class AskTracing:
    def __init__(
        self, metadata: Mapping[str, str], hasher: LearnerHasher | None, client: langsmith.Client | None = None
    ) -> None:
        self._metadata = dict(metadata)
        self._hasher = hasher
        self._client = client  # None: LangSmith's default client; tests pass a recording one

    @contextmanager
    def trace(self, run: AskRun) -> Iterator[AskTrace]:
        metadata: dict[str, object] = {**self._metadata, "limited": run.document_ids is not None}
        if run.thread_id is not None:
            metadata["thread_id"] = run.thread_id
        if self._hasher is not None:
            metadata["learner_hash"] = self._hasher(run.user_id)
        trace = langsmith.trace(
            "ask",
            run_id=run.run_id,
            inputs={"question": run.question, "document_ids": run.document_ids},
            metadata=metadata,
            client=self._client,
        )
        with never_raising(trace, None) as root:
            yield AskTrace(root)
