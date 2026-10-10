"""The count of citation highlights the viewer couldn't draw (PRD §10.1)."""

from abc import ABC, abstractmethod
from datetime import date


class HighlightMissCounter(ABC):
    @abstractmethod
    def increment(self, day: date) -> None:
        """Add one to that day's count."""
