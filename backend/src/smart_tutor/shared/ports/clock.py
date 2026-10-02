"""Clock port, so time-based rules (idle records, reports) are testable."""

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current time, timezone-aware (UTC)."""
