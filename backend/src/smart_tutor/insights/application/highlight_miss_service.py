"""Count a "Couldn't highlight" view: one number per UTC day, never who, which chunk, or what text."""

from datetime import UTC

from smart_tutor.insights.ports.highlight_misses import HighlightMissCounter
from smart_tutor.shared.ports.clock import Clock


class HighlightMissService:
    def __init__(self, counter: HighlightMissCounter, clock: Clock) -> None:
        self._counter = counter
        self._clock = clock

    def record(self) -> None:
        self._counter.increment(self._clock.now().astimezone(UTC).date())
