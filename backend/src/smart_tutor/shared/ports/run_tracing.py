"""Groups one unit of work's model calls under a named trace (PRD §10.4)."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext

from smart_tutor.shared.domain.ids import UserId


class RunTracing(ABC):
    @abstractmethod
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]:
        """Model calls made inside trace as children of a run named `name`. The learner appears in it only as a keyed
        hash of `user_id`."""


class NoRunTracing(RunTracing):
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]:
        return nullcontext()
