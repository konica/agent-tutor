"""Upload rate limits and daily caps (PRD §11, US-9, D27): a rolling hour and a calendar day in the app time zone."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

HOUR = timedelta(hours=1)


class LimitWindow(StrEnum):
    HOUR = "hour"  # rolling: the last 60 minutes
    DAY = "day"  # calendar: midnight to midnight in the app time zone


@dataclass(frozen=True)
class UploadBlock:
    """Which limit was reached and when the learner can upload again."""

    window: LimitWindow
    retry_at: datetime


def _midnight(now: datetime, tz: ZoneInfo, days: int = 0) -> datetime:
    return datetime.combine(now.astimezone(tz).date() + timedelta(days=days), time(), tzinfo=tz)


@dataclass(frozen=True)
class UploadLimits:
    per_hour: int
    per_day: int

    def __post_init__(self) -> None:
        if self.per_hour <= 0 or self.per_day <= 0:
            raise ValueError("Upload limits must be positive")

    def since(self, now: datetime, tz: ZoneInfo) -> datetime:
        """The earliest upload time that can still count toward either limit."""
        return min(now - HOUR, _midnight(now, tz))

    def check(self, created: Iterable[datetime], now: datetime, tz: ZoneInfo) -> UploadBlock | None:
        """None while another upload is allowed; otherwise the limit that ends last (a tie reports the day)."""
        times = sorted(created)
        blocks: list[UploadBlock] = []
        in_hour = [t for t in times if t > now - HOUR]
        if len(in_hour) >= self.per_hour:
            # Allowed again once enough of the oldest uploads leave the window.
            blocks.append(UploadBlock(LimitWindow.HOUR, in_hour[len(in_hour) - self.per_hour] + HOUR))
        start = _midnight(now, tz)
        if sum(1 for t in times if t >= start) >= self.per_day:
            blocks.append(UploadBlock(LimitWindow.DAY, _midnight(now, tz, days=1)))
        return max(blocks, key=lambda b: (b.retry_at, b.window is LimitWindow.DAY), default=None)


def limit_time_label(at: datetime, tz: ZoneInfo) -> str:
    """'11:40 (GMT+7)': the time a limit ends, shown in the app time zone (D27)."""
    local = at.astimezone(tz)
    offset = local.utcoffset() or timedelta()
    minutes = int(offset.total_seconds()) // 60
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    zone = "GMT" if minutes == 0 else f"GMT{sign}{hours}" + (f":{rest:02d}" if rest else "")
    return f"{local:%H:%M} ({zone})"


class UploadLimitReachedError(Exception):
    def __init__(self, block: UploadBlock, limits: UploadLimits, tz: ZoneInfo) -> None:
        super().__init__(f"Upload limit reached. You can upload again at {limit_time_label(block.retry_at, tz)}.")
        self.block, self.limits = block, limits
