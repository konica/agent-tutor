"""Each ask is one trace named `ask` (PRD §10.4): where and with which models it ran, for which thread, whether the
search was limited to the conversation's documents, and, once done, the decline code and how many chunks the model was
given. The learner appears only as a keyed hash; the token stays in runtime context (ADR 0007)."""

import uuid
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass

from smart_tutor.shared.domain.ids import UserId


@dataclass(frozen=True)
class AskRun:
    run_id: uuid.UUID  # the trace's id; the API keeps it with the turn
    thread_id: str | None
    user_id: UserId  # hashed before it reaches the trace
    question: str
    document_ids: list[str] | None


class AskTrace(ABC):
    @abstractmethod
    def finish(self, answer: str, decline: str | None, chunks: int) -> None:
        """What the ask ended with: a decline gives the model no chunks."""

    @abstractmethod
    def fail(self, code: str) -> None:
        """The ask ended with an error event; the learner saw `code`."""


class AskTracing(ABC):
    @abstractmethod
    def trace(self, run: AskRun) -> AbstractContextManager[AskTrace]:
        """The graph's runs inside nest under the ask; leaving the block ends the trace, finished or not. Tracing never
        fails the ask (#229)."""


class NoAskTrace(AskTrace):
    def finish(self, answer: str, decline: str | None, chunks: int) -> None:
        pass

    def fail(self, code: str) -> None:
        pass


class NoAskTracing(AskTracing):
    def trace(self, run: AskRun) -> AbstractContextManager[AskTrace]:
        return nullcontext(NoAskTrace())
