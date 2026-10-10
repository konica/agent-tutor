"""In-memory highlight-miss counter."""

from datetime import date

from smart_tutor.insights.ports.highlight_misses import HighlightMissCounter


class InMemoryHighlightMisses(HighlightMissCounter):
    def __init__(self) -> None:
        self.counts: dict[date, int] = {}

    def increment(self, day: date) -> None:
        self.counts[day] = self.counts.get(day, 0) + 1
