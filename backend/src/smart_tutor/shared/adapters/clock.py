from datetime import UTC, datetime

from smart_tutor.shared.ports.clock import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)
