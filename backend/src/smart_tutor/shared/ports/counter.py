"""A content-free counter (PRD §10.1): one number that something happened, never what or for whom."""

from abc import ABC, abstractmethod


class Counter(ABC):
    @abstractmethod
    async def increment(self) -> None:
        """Add one. Never raises: a count that can't be recorded is logged, and the caller goes on."""
