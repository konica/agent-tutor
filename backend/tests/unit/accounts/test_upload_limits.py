from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fakes import FakeParameterStore
from smart_tutor.accounts.application import (
    LimitWindow,
    UploadBlock,
    UploadLimitReachedError,
    UploadLimits,
    limit_time_label,
    load_upload_limits,
)
from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError

TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # GMT+7
LIMITS = UploadLimits(per_hour=20, per_day=100)


def gmt7(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ).astimezone(UTC)


def test_under_both_limits_is_not_blocked() -> None:
    now = gmt7(10, 11, 0)
    assert LIMITS.check([now - timedelta(minutes=m) for m in range(19)], now, TZ) is None


def test_the_21st_in_an_hour_waits_for_the_oldest_to_leave_the_window() -> None:
    now = gmt7(10, 11, 0)
    created = [gmt7(10, 10, 40) + timedelta(minutes=m) for m in range(20)]  # 10:40 … 10:59
    assert LIMITS.check(created, now, TZ) == UploadBlock(LimitWindow.HOUR, gmt7(10, 11, 40))


def test_an_upload_exactly_an_hour_old_no_longer_counts() -> None:
    now = gmt7(10, 11, 40)
    created = [gmt7(10, 10, 40) + timedelta(minutes=m) for m in range(20)]
    assert LIMITS.check(created, now, TZ) is None


def test_the_101st_in_a_gmt7_day_waits_until_midnight_gmt7() -> None:
    now = gmt7(10, 15, 0)
    created = [gmt7(10, 0, 0) + timedelta(minutes=7 * m) for m in range(100)]  # 00:00 … 11:33, never 20 in an hour
    assert LIMITS.check(created, now, TZ) == UploadBlock(LimitWindow.DAY, gmt7(11, 0, 0))


def test_the_daily_count_resets_at_midnight_gmt7() -> None:
    created = [gmt7(10, 0, 0) + timedelta(minutes=7 * m) for m in range(100)]
    assert LIMITS.check(created, gmt7(10, 23, 59), TZ) is not None
    assert LIMITS.check(created, gmt7(11, 0, 0), TZ) is None


def test_uploads_before_midnight_gmt7_but_on_the_same_utc_day_do_not_count_today() -> None:
    # 06:30 GMT+7 on the 11th is 23:30 UTC on the 10th: uploads from 01:00–06:00 GMT+7 the 10th are a different day.
    created = [gmt7(10, 1, 0) + timedelta(minutes=3 * m) for m in range(100)]
    assert LIMITS.check(created, gmt7(11, 6, 30), TZ) is None


def test_with_both_hit_the_later_end_wins() -> None:
    now = gmt7(10, 23, 50)
    created = [gmt7(10, 0, 0) + timedelta(minutes=8 * m) for m in range(80)] + [
        gmt7(10, 23, 30) + timedelta(seconds=30 * m) for m in range(20)
    ]
    assert LIMITS.check(created, now, TZ) == UploadBlock(LimitWindow.HOUR, gmt7(11, 0, 30))


def test_with_both_ending_at_the_same_time_the_daily_cap_is_reported() -> None:
    now = gmt7(10, 23, 30)
    created = [gmt7(10, 0, 0) + timedelta(minutes=8 * m) for m in range(80)] + [
        gmt7(10, 23, 0) + timedelta(seconds=30 * m) for m in range(20)
    ]
    assert LIMITS.check(created, now, TZ) == UploadBlock(LimitWindow.DAY, gmt7(11, 0, 0))


def test_since_covers_the_hour_and_the_day() -> None:
    assert LIMITS.since(gmt7(10, 15, 0), TZ) == gmt7(10, 0, 0)
    assert LIMITS.since(gmt7(10, 0, 20), TZ) == gmt7(9, 23, 20)


def test_labels_the_time_in_the_app_zone() -> None:
    assert limit_time_label(gmt7(10, 11, 40), TZ) == "11:40 (GMT+7)"
    assert limit_time_label(gmt7(11, 0, 0), TZ) == "00:00 (GMT+7)"
    assert limit_time_label(datetime(2026, 10, 10, 6, 0, tzinfo=UTC), ZoneInfo("Asia/Kolkata")) == "11:30 (GMT+5:30)"
    assert limit_time_label(datetime(2026, 10, 10, 6, 0, tzinfo=UTC), ZoneInfo("UTC")) == "06:00 (GMT)"


def test_the_error_says_when_uploads_open_again() -> None:
    error = UploadLimitReachedError(UploadBlock(LimitWindow.HOUR, gmt7(10, 11, 40)), LIMITS, TZ)
    assert str(error) == "Upload limit reached. You can upload again at 11:40 (GMT+7)."
    assert error.block.window is LimitWindow.HOUR and error.limits is LIMITS


@pytest.mark.parametrize(("hour", "day"), [(0, 100), (20, 0), (-1, 100)])
def test_limits_must_be_positive(hour: int, day: int) -> None:
    with pytest.raises(ValueError):
        UploadLimits(per_hour=hour, per_day=day)


HOUR_P, DAY_P = "/smart-tutor/max-uploads-per-hour", "/smart-tutor/max-uploads-per-day"


def test_loads_the_limits_from_parameters() -> None:
    store = FakeParameterStore({HOUR_P: "20", DAY_P: "100"})
    assert load_upload_limits(store, HOUR_P, DAY_P) == UploadLimits(per_hour=20, per_day=100)


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "1.5", ""])
def test_a_bad_value_names_the_parameter(bad: str) -> None:
    with pytest.raises(ValueError, match=DAY_P):
        load_upload_limits(FakeParameterStore({HOUR_P: "20", DAY_P: bad}), HOUR_P, DAY_P)


def test_a_missing_parameter_is_not_defaulted() -> None:
    with pytest.raises(ParameterNotFoundError, match=HOUR_P):
        load_upload_limits(FakeParameterStore({DAY_P: "100"}), HOUR_P, DAY_P)
