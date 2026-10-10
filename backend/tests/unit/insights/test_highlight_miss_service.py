from datetime import UTC, date, datetime, timedelta, timezone

from fakes import FixedClock, InMemoryHighlightMisses
from smart_tutor.insights.application import HighlightMissService


def test_counts_misses_per_day() -> None:
    counter, clock = InMemoryHighlightMisses(), FixedClock(datetime(2026, 10, 9, 9, 0, tzinfo=UTC))
    service = HighlightMissService(counter, clock)

    service.record()
    service.record()
    clock.current += timedelta(days=1)
    service.record()

    assert counter.counts == {date(2026, 10, 9): 2, date(2026, 10, 10): 1}


def test_the_day_is_the_utc_day() -> None:
    counter = InMemoryHighlightMisses()
    # 23:30 on 9 October in UTC-5 is already 10 October in UTC
    clock = FixedClock(datetime(2026, 10, 9, 23, 30, tzinfo=timezone(timedelta(hours=-5))))

    HighlightMissService(counter, clock).record()

    assert counter.counts == {date(2026, 10, 10): 1}
