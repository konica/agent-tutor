"""A clock that says what the test tells it."""

from datetime import UTC, datetime

from smart_tutor.shared.ports.clock import Clock


class FixedClock(Clock):
    def __init__(self, now: datetime = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current
