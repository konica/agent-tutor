# Upload Rate Limits and Daily Caps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse a learner's presigned upload with `429` and a retry-at time once they reach 20 uploads in a rolling hour or 100 in a GMT+7 day, and make the Library disable Upload and say when it opens again.

**Architecture:** `accounts` owns the policy (`UploadLimits.check`, a pure domain rule over upload times, the clock's `now`, and the app time zone) and loads it from SSM. `knowledge.UploadService.start_upload` locks the learner's uploads, reads their recent upload times from the `uploads` table, asks the policy, and raises `accounts`' `UploadLimitReachedError` before presigning. The API maps that to `429` with a JSON body and `Retry-After`, and adds `GET /uploads/rate-limit` so the Library can show the state on load.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / PostgreSQL advisory locks / zoneinfo; React + TypeScript + Vitest; AWS CDK (SSM parameters).

**Spec:** GitHub issue #66 ("Upload rate limits and daily caps"); PRD `sdd/prd.md` v2.30 §8 US-2 (fourth criterion), US-9 (429 with retry time, GMT+7, rolling shorter windows), §11 (20/hour, 100/day, duplicates and failed uploads count), D24, D27. Mockup state `library-rate-limited@v0.10`.

## Global Constraints

- Limits: **20 uploads per rolling hour**, **100 per GMT+7 calendar day** (midnight to midnight in `app-time-zone`, `Asia/Ho_Chi_Minh`), per learner. Values come from SSM, not code: `/smart-tutor/max-uploads-per-hour` = `20`, `/smart-tutor/max-uploads-per-day` = `100`.
- Every row in `uploads` counts (each presigned POST creates one): duplicates, failed processing, and presigns whose file never arrived. Deleting a document does not remove its upload row.
- No limit on the number of documents (D24).
- The 429 message and the Library text use the time in GMT+7 as `HH:MM` 24-hour with the zone label: `You can upload again at 11:40 (GMT+7)`; the daily cap reads `00:00 (GMT+7)`.
- Show only the limit that was hit. When both are hit, show the one that ends later (tie → daily).
- One learner's uploads never count toward another's; the status endpoint reports only the caller's.
- Module rules (`backend/AGENTS.md`): `accounts` imports only `shared`; `knowledge` uses `accounts` only through `smart_tutor.accounts.application`; `apps` is the leaf. Run `PYTHONUTF8=1 uv run lint-imports`.
- Out of scope: chat rate limits (`rate_limit_per_minute` stays untouched).
- UI: rebuild the mockup with `web/src/components/` (Banner variant `attn`); never copy prototype HTML/CSS. Visual rules in `DESIGN.md`.

## Review Focus

1. **Two uploads started at the same moment by one learner at 19 uploads** — expect exactly one to succeed. Task 2 takes a per-learner `pg_advisory_xact_lock` before counting; Task 2's integration test pins that the lock is taken inside the same transaction as the count.
2. **An upload exactly one hour old** — the rolling window is `created_at > now - 1h`, so it no longer counts and `retry_at` equals the oldest counted upload + 1 hour. Task 1 pins the boundary.
3. **23:50 GMT+7 with both limits hit** — the hourly limit can end after midnight; expect the later time (hourly) and its message. Task 1 pins it.
4. **A file batch that hits the limit mid-way in the browser** — files still queued must not each call the API and each show "Upload failed"; they get "Not uploaded. Upload limit reached." and the banner appears. Task 4 pins it.
5. **The Library left open until the limit ends** — Upload re-enables at `retry_at` without a reload. Task 4 pins it with fake timers.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `backend/src/smart_tutor/accounts/domain/upload_limits.py` | `LimitWindow`, `UploadBlock`, `UploadLimits` (the rule), `UploadLimitReachedError`, `limit_time_label` |
| Create `backend/src/smart_tutor/accounts/application/upload_limits.py` | `load_upload_limits` from the `ParameterStore` |
| Modify `backend/src/smart_tutor/accounts/application/__init__.py` | Public API exports |
| Modify `backend/src/smart_tutor/accounts/README.md` | Document the classes and rules |
| Modify `backend/src/smart_tutor/knowledge/ports/library.py` | `UploadRepository.lock_learner`, `created_since` |
| Modify `backend/src/smart_tutor/knowledge/adapters/sql_library.py` | SQL for both |
| Modify `backend/tests/fakes/knowledge.py` | Fake for both |
| Modify `backend/src/smart_tutor/knowledge/application/upload_service.py` | Enforce limits; `upload_block` |
| Modify `backend/src/smart_tutor/knowledge/README.md` | Document enforcement |
| Modify `backend/src/smart_tutor/shared/config.py` | Two parameter names |
| Modify `backend/src/smart_tutor/apps/api/services.py`, `apps/api/routes/knowledge.py` | Wiring, 429, `GET /uploads/rate-limit` |
| Modify `backend/tests/fakes/api.py`, `backend/tests/fakes/parameters.py` | `TEST_UPLOAD_LIMITS`, wiring |
| Create `backend/tests/unit/accounts/__init__.py`, `test_upload_limits.py` | Domain + loader tests |
| Modify `backend/tests/unit/knowledge/test_upload_service.py` | Service tests |
| Modify `backend/tests/integration/knowledge/test_sql_library.py` | SQL adapter tests |
| Modify `backend/tests/unit/apps/api/test_knowledge_routes.py` | Route tests; snapshot via `test_openapi_snapshot.py` |
| Create `backend/tests/isolation/test_upload_limits.py` | Isolation |
| Modify `local/localstack/init/ready.d/10-smart-tutor.sh`, `deploy/on-premise/compose.yaml`, `infra/smart_tutor_infra/stacks/config.py`, `infra/tests/test_config_stack.py` | SSM parameters |
| Regenerate `web/src/api/openapi.json`, `web/src/api/generated/*` | `make api-client` |
| Modify `web/src/time.ts` (+ create `web/src/time.test.ts`) | `limitTime(date)` → `"11:40 (GMT+7)"` |
| Modify `web/src/api/documents.ts`, `documents.test.ts` | `UploadLimitError`, `loadUploadRateLimit` |
| Modify `web/src/features/library/LibraryPage.tsx`, `LibraryPage.test.tsx` | Banner, disabled Upload and drop |

---

### Task 1: `accounts` upload-limit policy

**Files:**
- Create: `backend/src/smart_tutor/accounts/domain/upload_limits.py`
- Create: `backend/src/smart_tutor/accounts/application/upload_limits.py`
- Modify: `backend/src/smart_tutor/accounts/application/__init__.py`
- Modify: `backend/src/smart_tutor/accounts/README.md`
- Create: `backend/tests/unit/accounts/__init__.py` (empty), `backend/tests/unit/accounts/test_upload_limits.py`

**Interfaces:**
- Consumes: `smart_tutor.shared.ports.parameter_store.ParameterStore` (`get(name) -> str`, raises `ParameterNotFoundError`); `fakes.FakeParameterStore`.
- Produces (all exported from `smart_tutor.accounts.application`):
  - `class LimitWindow(StrEnum)`: `HOUR = "hour"`, `DAY = "day"`
  - `@dataclass(frozen=True) class UploadBlock`: `window: LimitWindow`, `retry_at: datetime` (aware, UTC-comparable)
  - `@dataclass(frozen=True) class UploadLimits`: `per_hour: int`, `per_day: int`; `since(now: datetime, tz: ZoneInfo) -> datetime` (earliest `created_at` that can still count); `check(created: Iterable[datetime], now: datetime, tz: ZoneInfo) -> UploadBlock | None`
  - `def limit_time_label(at: datetime, tz: ZoneInfo) -> str` → `"11:40 (GMT+7)"`
  - `class UploadLimitReachedError(Exception)`: attributes `block: UploadBlock`, `limits: UploadLimits`; `str(e)` == `"Upload limit reached. You can upload again at 11:40 (GMT+7)."`
  - `def load_upload_limits(store: ParameterStore, per_hour_param: str, per_day_param: str) -> UploadLimits`

- [ ] **Step 1: Write the failing tests** in `backend/tests/unit/accounts/test_upload_limits.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/unit/accounts -q`
Expected: FAIL at import (`cannot import name 'LimitWindow'`).

- [ ] **Step 3: Implement the domain** in `backend/src/smart_tutor/accounts/domain/upload_limits.py`:

```python
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
```

- [ ] **Step 4: Implement the loader** in `backend/src/smart_tutor/accounts/application/upload_limits.py`:

```python
"""Upload limits from SSM (PRD §9.4 Settings), read once at startup by the API."""

from smart_tutor.accounts.domain.upload_limits import UploadLimits
from smart_tutor.shared.ports.parameter_store import ParameterStore


def _positive(store: ParameterStore, name: str) -> int:
    raw = store.get(name)
    if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
        raise ValueError(f"{name} must be a positive whole number, got {raw!r}")
    return int(raw)


def load_upload_limits(store: ParameterStore, per_hour_param: str, per_day_param: str) -> UploadLimits:
    return UploadLimits(per_hour=_positive(store, per_hour_param), per_day=_positive(store, per_day_param))
```

Replace `backend/src/smart_tutor/accounts/application/__init__.py` with:

```python
"""accounts.application: Use-case services. This package is the module's public API for other modules."""

from smart_tutor.accounts.application.upload_limits import load_upload_limits
from smart_tutor.accounts.domain.upload_limits import (
    LimitWindow,
    UploadBlock,
    UploadLimitReachedError,
    UploadLimits,
    limit_time_label,
)

__all__ = [
    "LimitWindow",
    "UploadBlock",
    "UploadLimitReachedError",
    "UploadLimits",
    "limit_time_label",
    "load_upload_limits",
]
```

(Keep whatever docstring the existing `__init__.py` has if it differs; only add the imports and `__all__`.)

- [ ] **Step 5: Run tests, then lint/types/imports**

Run: `cd backend && uv run pytest tests/unit/accounts -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: all pass.

- [ ] **Step 6: Update `backend/src/smart_tutor/accounts/README.md`** — change the Key classes line to: `**Key classes:** \`UploadLimits\` (\`per_hour\`, \`per_day\`; \`check(created, now, tz)\` returns an \`UploadBlock\` (\`window\` hour or day, \`retry_at\`) or None; \`since(now, tz)\`), \`UploadLimitReachedError\`, \`limit_time_label\`; loader \`load_upload_limits\` (SSM \`max-uploads-per-hour\`, \`max-uploads-per-day\`). Service \`UsageService\` (token usage) arrives with US-9. Release 3 adds \`Learner\` and \`LearnerService\`.` and append to Rules: `The hour is rolling (an upload counts while \`created_at > now − 1 h\`); the day runs midnight to midnight in the app time zone (D27). When both are reached, the one that ends later is reported (a tie reports the day). \`knowledge\` counts the learner's \`uploads\` rows and asks \`UploadLimits.check\` before presigning.`

- [ ] **Step 7: Commit**

```bash
git add backend/src/smart_tutor/accounts backend/tests/unit/accounts
git commit -m "Add the upload rate-limit policy to accounts" -m "PRD §11 and D27: 20 per rolling hour and 100 per GMT+7 day, loaded from SSM. A pure rule so knowledge can enforce it against the uploads table (#66)."
```

---

### Task 2: Enforce the limits when an upload starts (`knowledge`)

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (`UploadRepository`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (`_Uploads`)
- Modify: `backend/tests/fakes/knowledge.py` (`_Uploads`)
- Modify: `backend/tests/fakes/parameters.py` (add `TEST_UPLOAD_LIMITS`), `backend/tests/fakes/__init__.py` (export it)
- Modify: `backend/src/smart_tutor/knowledge/application/upload_service.py`
- Modify: every `UploadService(` construction: `backend/tests/unit/knowledge/test_upload_service.py`, `backend/tests/fakes/api.py`, `backend/src/smart_tutor/apps/api/services.py` (find others with `grep -rn "UploadService(" backend`)
- Modify: `backend/src/smart_tutor/knowledge/README.md`
- Test: `backend/tests/unit/knowledge/test_upload_service.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Consumes (Task 1): `from smart_tutor.accounts.application import UploadBlock, UploadLimitReachedError, UploadLimits`; `UploadLimits.since(now, tz)`, `UploadLimits.check(created, now, tz)`.
- Produces:
  - `UploadRepository.lock_learner(user_id: UserId) -> None` — serializes concurrent upload starts of one learner until the unit of work ends.
  - `UploadRepository.created_since(user_id: UserId, since: datetime) -> list[datetime]` — `created_at` of the learner's uploads with `created_at >= since`.
  - `UploadService.__init__(uow, objects, clock, limits: FileLimits, *, rate: UploadLimits, time_zone: ZoneInfo, new_id=new_uuid)` — `rate`, `time_zone`, and `new_id` are keyword-only; `rate` and `time_zone` are required. Update `make()` in the test to pass `new_id=`.
  - `UploadService.rate_limits -> UploadLimits` (property)
  - `UploadService.now() -> datetime` — the service clock's time (the route computes `Retry-After` from it)
  - `Settings.max_uploads_per_hour_param`, `Settings.max_uploads_per_day_param` and the `apps/api/services.py` wiring (done here because the constructor requires them; code in Task 3 Step 3)
  - `UploadService.upload_block(user_id: UserId) -> UploadBlock | None`
  - `UploadService.start_upload` raises `UploadLimitReachedError` and stores nothing when blocked.
  - `fakes.TEST_UPLOAD_LIMITS = UploadLimits(per_hour=20, per_day=100)`; `fakes.APP_TZ = ZoneInfo("Asia/Ho_Chi_Minh")` (add `APP_TZ` to `fakes/parameters.py` too and export it).

- [ ] **Step 1: Write the failing unit tests.** In `backend/tests/unit/knowledge/test_upload_service.py` change `make` and the `FileLimits` test to the new constructor, and add:

```python
from datetime import UTC, datetime, timedelta

from fakes import APP_TZ, TEST_UPLOAD_LIMITS
from smart_tutor.accounts.application import LimitWindow, UploadLimitReachedError, UploadLimits


def make(ids: list[str] | None = None, clock: FixedClock | None = None, rate: UploadLimits = TEST_UPLOAD_LIMITS):
    library, objects = InMemoryLibrary(), FakeObjectStore()
    it = iter(ids or [UPLOAD, DOC])
    service = UploadService(
        library.unit_of_work, objects, clock or FixedClock(), TEST_LIMITS, rate=rate, time_zone=APP_TZ,
        new_id=lambda: next(it),
    )
    return service, library, objects


def counting() -> tuple[UploadService, InMemoryLibrary, FakeObjectStore, FixedClock]:
    """Fresh ids for every upload, a small limit (3 per hour, 5 per day), and a clock the test moves."""
    library, objects, clock = InMemoryLibrary(), FakeObjectStore(), FixedClock(datetime(2026, 10, 10, 3, 0, tzinfo=UTC))
    service = UploadService(
        library.unit_of_work, objects, clock, TEST_LIMITS, rate=UploadLimits(per_hour=3, per_day=5), time_zone=APP_TZ
    )
    return service, library, objects, clock


def test_the_upload_over_the_hourly_limit_is_refused_and_stores_nothing() -> None:
    service, library, objects, clock = counting()
    for minute in range(3):
        clock.current = datetime(2026, 10, 10, 3, minute * 10, tzinfo=UTC)
        service.start_upload(UserId("ada"), f"{minute}.pdf")

    clock.current = datetime(2026, 10, 10, 3, 30, tzinfo=UTC)
    with pytest.raises(UploadLimitReachedError) as refused:
        service.start_upload(UserId("ada"), "fourth.pdf")

    assert refused.value.block.window is LimitWindow.HOUR
    assert refused.value.block.retry_at == datetime(2026, 10, 10, 4, 0, tzinfo=UTC)
    assert len(library.state.uploads) == 3 and len(library.state.documents) == 3 and len(objects.presigned) == 3


def test_duplicate_and_failed_uploads_count() -> None:
    service, library, _, clock = counting()
    for n in range(3):
        clock.current = datetime(2026, 10, 10, 3, n, tzinfo=UTC)
        started = service.start_upload(UserId("ada"), f"{n}.pdf")
        library.state.documents.pop(started.document_id)  # a duplicate's placeholder goes away; a failed one stays
    with pytest.raises(UploadLimitReachedError):
        service.start_upload(UserId("ada"), "next.pdf")


def test_the_daily_cap_resets_at_midnight_gmt7() -> None:
    service, _, _, clock = counting()
    # 5 uploads, one every 2 hours from 06:00 to 14:00 GMT+7 on the 10th (23:00 UTC the 9th … 07:00 UTC the 10th).
    for n in range(5):
        clock.current = datetime(2026, 10, 9, 23, 0, tzinfo=UTC) + timedelta(hours=2 * n)
        service.start_upload(UserId("ada"), f"{n}.pdf")

    clock.current = datetime(2026, 10, 10, 16, 59, tzinfo=UTC)  # 23:59 GMT+7
    with pytest.raises(UploadLimitReachedError) as refused:
        service.start_upload(UserId("ada"), "late.pdf")
    assert refused.value.block.window is LimitWindow.DAY
    assert refused.value.block.retry_at == datetime(2026, 10, 10, 17, 0, tzinfo=UTC)  # 00:00 GMT+7 the 11th

    clock.current = datetime(2026, 10, 10, 17, 0, tzinfo=UTC)  # 00:00 GMT+7
    service.start_upload(UserId("ada"), "tomorrow.pdf")


def test_upload_block_reports_the_callers_state_only() -> None:
    service, _, _, clock = counting()
    for n in range(3):
        service.start_upload(UserId("ada"), f"{n}.pdf")
    assert service.upload_block(UserId("ada")) is not None
    assert service.upload_block(UserId("bob")) is None
    service.start_upload(UserId("bob"), "b.pdf")  # Ada's uploads never count toward Bob's limits
```

Also add `"locked_learners"` assertion to the existing first test is not needed; instead add:

```python
def test_start_upload_locks_the_learner_before_counting() -> None:
    service, library, _ = make()
    service.start_upload(UserId("ada"), "a.pdf")
    assert library.locked_learners == ["ada"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/knowledge/test_upload_service.py -q`
Expected: FAIL (`unexpected keyword argument 'rate'` / import errors).

- [ ] **Step 3: Add the port methods** to `UploadRepository` in `backend/src/smart_tutor/knowledge/ports/library.py` (add `from datetime import datetime`):

```python
    @abstractmethod
    def lock_learner(self, user_id: UserId) -> None:
        """Hold the learner's upload starts one at a time until this unit of work ends (limits count exactly)."""

    @abstractmethod
    def created_since(self, user_id: UserId, since: datetime) -> list[datetime]:
        """When each of the learner's uploads at or after `since` started (rate limits, PRD §11)."""
```

- [ ] **Step 4: Implement the fake** in `backend/tests/fakes/knowledge.py`: add `self.locked_learners: list[str] = []` to `InMemoryLibrary.__init__`; pass the library to `_Uploads` the way `_Contents` gets it (`_Uploads(self._staged, library)`), and add:

```python
    def lock_learner(self, user_id: UserId) -> None:
        self._library.locked_learners.append(user_id)

    def created_since(self, user_id: UserId, since: datetime) -> list[datetime]:
        return [u.created_at for u in self._s.uploads.values() if u.user_id == user_id and u.created_at >= since]
```

- [ ] **Step 5: Implement the SQL adapter** in `_Uploads` of `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (imports: `func`, `text` from sqlalchemy as needed, `datetime`):

```python
    def lock_learner(self, user_id: UserId) -> None:
        # A transaction-level advisory lock per learner: concurrent starts count one after another (released at commit).
        self._conn.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(literal("uploads:") + user_id, 0)))
        )

    def created_since(self, user_id: UserId, since: datetime) -> list[datetime]:
        rows = self._conn.execute(
            select(uploads.c.created_at).where(uploads.c.user_id == user_id, uploads.c.created_at >= since)
        )
        return [row.created_at for row in rows]
```

(`literal` from `sqlalchemy`. The index `uploads_user_created (user_id, created_at)` from migration 0002 serves the query; no migration.)

- [ ] **Step 6: Implement the service** in `backend/src/smart_tutor/knowledge/application/upload_service.py`:

```python
from zoneinfo import ZoneInfo

from smart_tutor.accounts.application import UploadBlock, UploadLimitReachedError, UploadLimits


class UploadService:
    def __init__(
        self,
        uow: Callable[[], LibraryUnitOfWork],
        objects: ObjectStore,
        clock: Clock,
        limits: FileLimits,
        *,
        rate: UploadLimits,
        time_zone: ZoneInfo,
        new_id: Callable[[], str] = new_uuid,
    ) -> None:
        self._uow, self._objects, self._clock, self._limits, self._new_id = uow, objects, clock, limits, new_id
        self._rate, self._tz = rate, time_zone

    @property
    def rate_limits(self) -> UploadLimits:
        return self._rate

    def start_upload(self, owner_id: UserId, file_name: str) -> StartedUpload:
        """Refuses with UploadLimitReachedError at the learner's hourly or daily limit; every started upload counts
        (duplicates and failed ones too, PRD §11)."""
        now = self._clock.now()
        upload = Upload(UploadId(self._new_id()), owner_id, now)
        document = Document.start_upload(DocumentId(self._new_id()), owner_id, upload.upload_id, file_name, now)
        with self._uow() as tx:
            tx.uploads.lock_learner(owner_id)
            block = self._rate.check(tx.uploads.created_since(owner_id, self._rate.since(now, self._tz)), now, self._tz)
            if block:
                raise UploadLimitReachedError(block, self._rate, self._tz)
            post = self._objects.presign_post(
                upload.key, content_type=PDF_CONTENT_TYPE, max_bytes=self._limits.max_bytes, expires_in=PRESIGN_SECONDS
            )
            tx.uploads.add(upload)
            tx.documents.add(document)
            tx.commit()
        return StartedUpload(document.document_id, upload.upload_id, post.url, post.fields)

    def upload_block(self, user_id: UserId) -> UploadBlock | None:
        """Whether the caller has reached an upload limit now, and until when (their own uploads only)."""
        now = self._clock.now()
        with self._uow() as tx:
            created = tx.uploads.created_since(user_id, self._rate.since(now, self._tz))
        return self._rate.check(created, now, self._tz)
```

Keep `Document.start_upload` before the transaction so `InvalidFileNameError` still stores nothing. Presigning is local signing (no network), so it is fine inside the transaction.

- [ ] **Step 7: Add `TEST_UPLOAD_LIMITS` and `APP_TZ`** to `backend/tests/fakes/parameters.py`:

```python
from zoneinfo import ZoneInfo

from smart_tutor.accounts.application import UploadLimits

TEST_UPLOAD_LIMITS = UploadLimits(per_hour=20, per_day=100)
APP_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
```

and export both from `backend/tests/fakes/__init__.py` (follow how `TEST_LIMITS` is exported). Update `backend/tests/fakes/api.py`: `UploadService(library.unit_of_work, objects, clock, TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ)`. Apply Task 3 Step 3 (the two `Settings` fields and the `services.py` wiring) verbatim now, since the constructor requires `rate` and `time_zone`. Also add to the service:

```python
    def now(self) -> datetime:
        return self._clock.now()
```

- [ ] **Step 8: Write the SQL integration test** in `backend/tests/integration/knowledge/test_sql_library.py`, following the file's fixtures for an engine/unit of work (read the top of the file first):

```python
def test_created_since_returns_only_the_learners_recent_uploads(uow_factory) -> None:  # use the file's fixture name
    t0 = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
    with uow_factory() as tx:
        tx.uploads.add(Upload(UploadId(str(uuid4())), UserId("ada"), t0 - timedelta(hours=2)))
        tx.uploads.add(Upload(UploadId(str(uuid4())), UserId("ada"), t0))
        tx.uploads.add(Upload(UploadId(str(uuid4())), UserId("bob"), t0))
        tx.commit()
    with uow_factory() as tx:
        tx.uploads.lock_learner(UserId("ada"))
        assert tx.uploads.created_since(UserId("ada"), t0 - timedelta(hours=1)) == [t0]
```

- [ ] **Step 9: Run tests and checks**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: all pass (integration tests are skipped without Compose; if `docker compose up -d` is running, also run `uv run pytest -m integration tests/integration/knowledge/test_sql_library.py -q`).

- [ ] **Step 10: Update `backend/src/smart_tutor/knowledge/README.md`**: in Key classes, `UploadService` gains "(`start_upload` refuses with `accounts`' `UploadLimitReachedError` at the learner's hourly or daily limit; `upload_block` answers `GET /uploads/rate-limit` for the caller only)"; add to Rules: "`start_upload` takes a per-learner advisory lock (`UploadRepository.lock_learner`), counts the learner's `uploads` rows since `UploadLimits.since` (every started upload counts: duplicates, failed, and never-sent ones; deleting a document keeps its upload row), and presigns only when `UploadLimits.check` allows it."

- [ ] **Step 11: Commit**

```bash
git add -A backend
git commit -m "Refuse an upload start at the learner's upload limit" -m "Counts the learner's uploads rows under a per-learner advisory lock so concurrent starts can't pass the limit together (#66)."
```

---

### Task 3: API, settings, and SSM parameters

**Files:**
- Modify: `backend/src/smart_tutor/shared/config.py`
- Modify: `backend/src/smart_tutor/apps/api/services.py`
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py`
- Modify: `backend/tests/unit/apps/api/test_knowledge_routes.py`; the OpenAPI snapshot used by `test_openapi_snapshot.py` (read that test to see how to refresh it)
- Create: `backend/tests/isolation/test_upload_limits.py`
- Modify: `local/localstack/init/ready.d/10-smart-tutor.sh`, `deploy/on-premise/compose.yaml`, `infra/smart_tutor_infra/stacks/config.py`, `infra/tests/test_config_stack.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: `UploadService.start_upload`, `.upload_block(user_id)`, `.rate_limits` (Task 2); `UploadLimitReachedError` (`.block.window`, `.block.retry_at`, `.limits`, `str()`), `load_upload_limits` (Task 1).
- Produces (HTTP, consumed by Task 4 through the generated client):
  - `GET /uploads/rate-limit`, operation id `get_upload_rate_limit` → `UploadRateLimitResponse { per_hour: int, per_day: int, limit: "hour" | "day" | null, retry_at: datetime | null }`
  - `POST /uploads` at a limit → `429`, header `Retry-After: <whole seconds, rounded up, ≥ 1>`, body `UploadLimitReachedResponse { detail: str, per_hour, per_day, limit: "hour" | "day", retry_at: datetime }`; documented with `responses={429: {"model": UploadLimitReachedResponse}}`.
  - Settings: `max_uploads_per_hour_param = "/smart-tutor/max-uploads-per-hour"`, `max_uploads_per_day_param = "/smart-tutor/max-uploads-per-day"`.

- [ ] **Step 1: Write the failing route tests** in `backend/tests/unit/apps/api/test_knowledge_routes.py` (read the top of the file and reuse its client/token setup helper; below, `client_for(services)` and `HEADERS` stand for it):

```python
from datetime import UTC, datetime

from fakes import APP_TZ, TEST_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary, api_services
from smart_tutor.accounts.application import UploadLimits
from smart_tutor.knowledge.application import UploadService


def limited_services(per_hour: int = 2, per_day: int = 100):
    library, objects = InMemoryLibrary(), FakeObjectStore()
    clock = FixedClock(datetime(2026, 10, 10, 4, 0, tzinfo=UTC))  # 11:00 GMT+7
    uploads = UploadService(
        library.unit_of_work, objects, clock, TEST_LIMITS, rate=UploadLimits(per_hour, per_day), time_zone=APP_TZ
    )
    return api_services(library, objects, clock=clock, uploads=uploads), clock


def test_the_upload_over_the_limit_is_429_with_the_time_it_opens_again() -> None:
    services, clock = limited_services()
    client = client_for(services)
    clock.current = datetime(2026, 10, 10, 3, 40, tzinfo=UTC)  # 10:40 GMT+7
    assert client.post("/uploads", json={"file_name": "a.pdf"}, headers=HEADERS).status_code == 201
    clock.current = datetime(2026, 10, 10, 3, 50, tzinfo=UTC)
    assert client.post("/uploads", json={"file_name": "b.pdf"}, headers=HEADERS).status_code == 201

    clock.current = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)
    refused = client.post("/uploads", json={"file_name": "c.pdf"}, headers=HEADERS)

    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "2400"
    assert refused.json() == {
        "detail": "Upload limit reached. You can upload again at 11:40 (GMT+7).",
        "per_hour": 2,
        "per_day": 100,
        "limit": "hour",
        "retry_at": "2026-10-10T04:40:00Z",
    }


def test_rate_limit_status_reports_the_open_and_the_limited_state() -> None:
    services, clock = limited_services(per_hour=1)
    client = client_for(services)
    assert client.get("/uploads/rate-limit", headers=HEADERS).json() == {
        "per_hour": 1, "per_day": 100, "limit": None, "retry_at": None
    }
    client.post("/uploads", json={"file_name": "a.pdf"}, headers=HEADERS)
    assert client.get("/uploads/rate-limit", headers=HEADERS).json() == {
        "per_hour": 1, "per_day": 100, "limit": "hour", "retry_at": "2026-10-10T05:00:00Z"
    }


def test_the_daily_cap_says_midnight_gmt7() -> None:
    services, _ = limited_services(per_hour=50, per_day=1)
    client = client_for(services)
    client.post("/uploads", json={"file_name": "a.pdf"}, headers=HEADERS)
    refused = client.post("/uploads", json={"file_name": "b.pdf"}, headers=HEADERS)
    assert refused.json()["detail"] == "Upload limit reached. You can upload again at 00:00 (GMT+7)."
    assert refused.json()["limit"] == "day"
```

(Match the exact datetime serialization the app produces — if FastAPI emits `"2026-10-10T04:40:00Z"` vs `"+00:00"`, follow the existing response tests for `created_at` and adjust the expected strings, not the code.)

- [ ] **Step 2: Write the failing isolation test** `backend/tests/isolation/test_upload_limits.py`:

```python
"""US-12 / #66: one learner's uploads never count toward another's limits, and the status reports only the caller's."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from fakes import APP_TZ, TEST_LIMITS, FakeObjectStore, FakeTokenVerifier, FixedClock, InMemoryLibrary, api_services
from smart_tutor.accounts.application import UploadLimits
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


def setup() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    clock = FixedClock(datetime(2026, 10, 10, 4, 0, tzinfo=UTC))
    uploads = UploadService(
        library.unit_of_work, objects, clock, TEST_LIMITS, rate=UploadLimits(per_hour=2, per_day=3), time_zone=APP_TZ
    )
    return TestClient(create_app(Settings(), verifier=verifier, services=api_services(library, objects, uploads=uploads)))


def test_a_learners_uploads_never_count_toward_anothers_limits() -> None:
    client = setup()
    for name in ("a1.pdf", "a2.pdf"):
        assert client.post("/uploads", json={"file_name": name}, headers=A).status_code == 201
    assert client.post("/uploads", json={"file_name": "a3.pdf"}, headers=A).status_code == 429

    assert client.get("/uploads/rate-limit", headers=B).json()["limit"] is None
    assert client.post("/uploads", json={"file_name": "b1.pdf"}, headers=B).status_code == 201
    assert client.post("/uploads", json={"file_name": "b2.pdf"}, headers=B).status_code == 201


def test_the_status_reports_only_the_callers_limit_and_takes_no_user() -> None:
    client = setup()
    for name in ("a1.pdf", "a2.pdf"):
        client.post("/uploads", json={"file_name": name}, headers=A)
    assert client.get("/uploads/rate-limit", headers=A).json()["limit"] == "hour"
    assert client.get("/uploads/rate-limit", headers=B, params={"user_id": "learner-a"}).json()["limit"] is None
```

- [ ] **Step 3: Settings and wiring** (already applied in Task 2 Step 7; verify it is present). In `backend/src/smart_tutor/shared/config.py`, after `max_processing_attempts_param`:

```python
    # Upload rate limits and daily caps per learner (PRD §11): a rolling hour and a day in app-time-zone, read once at
    # startup by the API.
    max_uploads_per_hour_param: str = "/smart-tutor/max-uploads-per-hour"
    max_uploads_per_day_param: str = "/smart-tutor/max-uploads-per-day"
```

In `backend/src/smart_tutor/apps/api/services.py`: import `from smart_tutor.accounts.application import load_upload_limits`; read the time zone once (`time_zone = ZoneInfo(params.get(settings.app_time_zone_param))`), pass it to `DocumentService(..., time_zone=time_zone)` and build:

```python
        uploads=UploadService(
            library,
            objects,
            SystemClock(),
            limits,
            rate=load_upload_limits(params, settings.max_uploads_per_hour_param, settings.max_uploads_per_day_param),
            time_zone=time_zone,
        ),
```

- [ ] **Step 4: Routes.** In `backend/src/smart_tutor/apps/api/routes/knowledge.py` (imports: `import math`, `from fastapi.responses import JSONResponse`, `from smart_tutor.accounts.application import UploadLimitReachedError`):

```python
class UploadRateLimitResponse(BaseModel):
    per_hour: int
    per_day: int
    limit: Literal["hour", "day"] | None  # the limit reached, null while the learner can upload
    retry_at: datetime | None  # when uploads open again


class UploadLimitReachedResponse(BaseModel):
    detail: str  # "Upload limit reached. You can upload again at 11:40 (GMT+7)."
    per_hour: int
    per_day: int
    limit: Literal["hour", "day"]
    retry_at: datetime
```

Change `start_upload`:

```python
@router.post(
    "/uploads",
    operation_id="start_upload",
    status_code=status.HTTP_201_CREATED,
    responses={429: {"model": UploadLimitReachedResponse, "description": "An upload limit is reached (PRD §11)"}},
)
def start_upload(
    body: StartUploadRequest, principal: CurrentPrincipal, uploads: Uploads
) -> StartUploadResponse | JSONResponse:
    try:
        started = uploads.start_upload(principal.user_id, body.file_name)
    except InvalidFileNameError as e:
        raise HTTPException(422, str(e)) from None
    except UploadLimitReachedError as e:
        wait = math.ceil((e.block.retry_at - uploads.now()).total_seconds())
        refused = UploadLimitReachedResponse(
            detail=str(e), per_hour=e.limits.per_hour, per_day=e.limits.per_day, limit=e.block.window.value,
            retry_at=e.block.retry_at,
        )
        return JSONResponse(refused.model_dump(mode="json"), status_code=429, headers={"Retry-After": str(max(wait, 1))})
    return StartUploadResponse(...)  # unchanged
```

If the return union upsets FastAPI's response-model inference, set `response_model=StartUploadResponse` on the decorator. `Retry-After` comes from the service's clock (`uploads.now()`), so the route test's `"2400"` holds with the fixed clock. Then add, **above** `@router.get("/uploads/{upload_id}"...)`:

```python
@router.get("/uploads/rate-limit", operation_id="get_upload_rate_limit")
def get_upload_rate_limit(principal: CurrentPrincipal, uploads: Uploads) -> UploadRateLimitResponse:
    """The caller's upload limits and, when one is reached, which and until when (PRD §11, US-9)."""
    block = uploads.upload_block(principal.user_id)
    return UploadRateLimitResponse(
        per_hour=uploads.rate_limits.per_hour,
        per_day=uploads.rate_limits.per_day,
        limit=block.window.value if block else None,
        retry_at=block.retry_at if block else None,
    )
```

Update the module docstring's first sentence to mention "the caller's upload limits".

- [ ] **Step 5: Run the backend tests**, refresh the OpenAPI snapshot the way `test_openapi_snapshot.py` documents, and run all checks:

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: all pass.

- [ ] **Step 6: SSM parameters everywhere they are declared.**
  - `local/localstack/init/ready.d/10-smart-tutor.sh`, after `max-processing-attempts` and before the app-time-zone comment:

    ```bash
    # Upload rate limits and daily caps per learner (PRD §11): the API refuses a presigned POST past them.
    awslocal ssm put-parameter --name /smart-tutor/max-uploads-per-hour --type String --value 20 --overwrite
    awslocal ssm put-parameter --name /smart-tutor/max-uploads-per-day --type String --value 100 --overwrite
    ```
  - `deploy/on-premise/compose.yaml` api env, after `SMART_TUTOR_MAX_PROCESSING_ATTEMPTS_PARAM`:

    ```yaml
          SMART_TUTOR_MAX_UPLOADS_PER_HOUR_PARAM: ${SSM_PATH:?}/max-uploads-per-hour
          SMART_TUTOR_MAX_UPLOADS_PER_DAY_PARAM: ${SSM_PATH:?}/max-uploads-per-day
    ```
  - `infra/smart_tutor_infra/stacks/config.py`: add `("max-uploads-per-hour", "20"), ("max-uploads-per-day", "100"),` to the tuple and mention "upload rate limits and daily caps" in the comment and module docstring.
  - `infra/tests/test_config_stack.py`: add assertions in the existing style:

    ```python
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-uploads-per-hour", "Value": "20"})
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-uploads-per-day", "Value": "100"})
    ```
  - Check `deploy/helm` for where `max-processing-attempts` or `MAX_PROCESSING_ATTEMPTS_PARAM` is set (`grep -rn "PROCESSING_ATTEMPTS" deploy infra`) and add the two new ones beside it if any exist.

Run: `cd infra && uv run pytest -q` — Expected: pass.

- [ ] **Step 7: Regenerate the web API client.** On Windows Git Bash without make, run the `api-client` target's command:

```bash
cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate
```

Expected: `web/src/api/generated/sdk.gen.ts` exports `getUploadRateLimit`; `types.gen.ts` has `UploadRateLimitResponse` and `UploadLimitReachedResponse`. Run `cd web && npm run build` to confirm it compiles.

- [ ] **Step 8: Commit**

```bash
git add -A backend local deploy infra web/src/api
git commit -m "Return 429 at the upload limit and report the caller's limit" -m "POST /uploads answers 429 with Retry-After and the time uploads open again in GMT+7; GET /uploads/rate-limit lets the Library show it on load. Limits are SSM parameters max-uploads-per-hour and max-uploads-per-day (#66)."
```

---

### Task 4: Library: limit banner, disabled Upload and drop

**Files:**
- Modify: `web/src/time.ts`; Create: `web/src/time.test.ts`
- Modify: `web/src/api/documents.ts`, `web/src/api/documents.test.ts`
- Modify: `web/src/features/library/LibraryPage.tsx`, `web/src/features/library/LibraryPage.test.tsx`

**Interfaces:**
- Consumes (Task 3, generated): `getUploadRateLimit` from `./generated/sdk.gen`; types `UploadRateLimitResponse`, `UploadLimitReachedResponse` from `./generated/types.gen`.
- Produces:
  - `time.ts`: `export function limitTime(at: Date): string` → `"11:40 (GMT+7)"` (24-hour, `APP_TIME_ZONE`, zone label from `timeZoneName: "shortOffset"`).
  - `documents.ts`: `export type UploadRateLimit = UploadRateLimitResponse;` `export class UploadLimitError extends Error { readonly rateLimit: UploadRateLimit }` (thrown by `uploadPdf` on 429; `message` is the server's `detail`); `export async function loadUploadRateLimit(apiClient?: Client): Promise<UploadRateLimit>`.
  - `LibraryPage` prop `loadRateLimit?: () => Promise<UploadRateLimit>`.

- [ ] **Step 1: Write the failing tests.**

`web/src/time.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { limitTime } from "./time";

describe("limitTime", () => {
  it("shows the time in GMT+7 on a 24-hour clock", () => {
    expect(limitTime(new Date("2026-10-10T04:40:00Z"))).toBe("11:40 (GMT+7)");
    expect(limitTime(new Date("2026-10-10T17:00:00Z"))).toBe("00:00 (GMT+7)");
  });
});
```

In `web/src/api/documents.test.ts` (add `loadUploadRateLimit`, `UploadLimitError` to the import):

```ts
describe("upload limits", () => {
  const limited = { detail: "Upload limit reached. You can upload again at 11:40 (GMT+7).", per_hour: 20, per_day: 100, limit: "hour", retry_at: "2026-10-10T04:40:00Z" };

  it("throws UploadLimitError with the limit on a 429 and posts nothing", async () => {
    const { apiClient } = api(() => json(limited, 429));
    const post = vi.fn(async () => 204);
    const error = await uploadPdf(new File(["%PDF"], "a.pdf", { type: "application/pdf" }), {}, apiClient, post).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(UploadLimitError);
    expect((error as UploadLimitError).rateLimit).toEqual({ per_hour: 20, per_day: 100, limit: "hour", retry_at: "2026-10-10T04:40:00Z" });
    expect((error as Error).message).toBe(limited.detail);
    expect(post).not.toHaveBeenCalled();
  });

  it("loads the caller's rate limit", async () => {
    const open = { per_hour: 20, per_day: 100, limit: null, retry_at: null };
    const { apiClient, fetch } = api(() => json(open));
    await expect(loadUploadRateLimit(apiClient)).resolves.toEqual(open);
    expect((fetch.mock.calls[0]![0] as Request).url).toBe("http://api.test/uploads/rate-limit");
  });
});
```

In `web/src/features/library/LibraryPage.test.tsx` (import `UploadLimitError`, `type UploadRateLimit`):

```ts
const open = async (): Promise<UploadRateLimit> => ({ per_hour: 20, per_day: 100, limit: null, retry_at: null });
const hourly = (retry_at: string): UploadRateLimit => ({ per_hour: 20, per_day: 100, limit: "hour", retry_at });
const LIMIT_TEXT = "You can upload up to 20 files per hour and 100 per day. You can upload again at 11:40 (GMT+7).";

describe("LibraryPage upload limits", () => {
  it("shows the limit and disables Upload when the learner is limited on load", async () => {
    const future = new Date(Date.now() + 30 * 60_000).toISOString();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={vi.fn()} loadRateLimit={async () => ({ ...hourly(future) })} />);
    expect(await screen.findByText("Upload limit reached.")).toBeVisible();
    expect(screen.getByText(/You can upload up to 20 files per hour and 100 per day\. You can upload again at \d\d:\d\d \(GMT\+7\)\./)).toBeVisible();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  });

  it("shows only the daily limit's time when the daily cap is hit", async () => {
    // retry_at is 00:00 GMT+7 tomorrow
    const midnight = new Date(); midnight.setUTCHours(17, 0, 0, 0); if (midnight.getTime() <= Date.now()) midnight.setUTCDate(midnight.getUTCDate() + 1);
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={vi.fn()} loadRateLimit={async () => ({ per_hour: 20, per_day: 100, limit: "day", retry_at: midnight.toISOString() })} />);
    expect(await screen.findByText(/You can upload again at 00:00 \(GMT\+7\)\./)).toBeVisible();
    expect(screen.queryByText(/11:40/)).toBeNull();
  });

  it("disables Choose PDFs on the first-run card too", async () => {
    const future = new Date(Date.now() + 30 * 60_000).toISOString();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} loadRateLimit={async () => hourly(future)} />);
    expect(await screen.findByText("Upload limit reached.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeDisabled();
  });

  it("stops a batch at the 429: the rest are not sent and the banner appears", async () => {
    const future = new Date(Date.now() + 30 * 60_000).toISOString();
    const upload = vi.fn(async () => {
      throw new UploadLimitError(hourly(future), "Upload limit reached. You can upload again at 11:40 (GMT+7).");
    });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={upload} loadRateLimit={open} />);
    await screen.findByText("lewis-rag-2020.pdf");
    const files = ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"].map((n) => new File(["%PDF"], n, { type: "application/pdf" }));
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), files);

    expect(await screen.findByText("Upload limit reached.")).toBeVisible();
    const notUploaded = screen.getByRole("list", { name: "Files not uploaded" });
    for (const f of files) expect(within(notUploaded).getByText(f.name)).toBeVisible();
    expect(within(notUploaded).getAllByText("Not uploaded. Upload limit reached.")).toHaveLength(5);
    expect(upload.mock.calls.length).toBeLessThanOrEqual(3); // only the files already sending when the 429 came
    expect(screen.queryByText(/Couldn't upload/)).toBeNull();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  });

  it("ignores dropped files while limited", async () => {
    const future = new Date(Date.now() + 30 * 60_000).toISOString();
    const upload = vi.fn();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={upload} loadRateLimit={async () => hourly(future)} />);
    await screen.findByText("Upload limit reached.");
    const file = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    fireEvent.drop(window, { dataTransfer: { files: [file], types: ["Files"] } });  // follow usePageDrop.test.tsx for the exact drop event shape
    await act(async () => {});
    expect(upload).not.toHaveBeenCalled();
  });

  it("enables Upload again when the limit ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const retryAt = new Date(Date.now() + 60_000).toISOString();
    let calls = 0;
    const loadRateLimit = async () => (calls++ === 0 ? hourly(retryAt) : { per_hour: 20, per_day: 100, limit: null, retry_at: null });
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={vi.fn()} loadRateLimit={loadRateLimit} />);
    expect(await screen.findByText("Upload limit reached.")).toBeVisible();
    await act(async () => { await vi.advanceTimersByTimeAsync(61_000); });
    await waitFor(() => expect(screen.queryByText("Upload limit reached.")).toBeNull());
    expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
  });
});
```

Existing `LibraryPage` tests don't pass `loadRateLimit`; the default calls the real API. Add `loadRateLimit={open}` wherever needed, or (simpler) make the page treat a failed status load as "not limited" so the existing tests stay green without edits — that is the required behavior anyway (the server still enforces).

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run src/time.test.ts src/api/documents.test.ts src/features/library/LibraryPage.test.tsx`
Expected: FAIL (missing exports / props).

- [ ] **Step 3: `web/src/time.ts`** — append:

```ts
// When a limit ends, as the Library shows it: "11:40 (GMT+7)" (PRD D27).
export function limitTime(at: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: APP_TIME_ZONE, hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "shortOffset" }).formatToParts(at);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("hour")}:${part("minute")} (${part("timeZoneName")})`;
}
```

- [ ] **Step 4: `web/src/api/documents.ts`** — add `getUploadRateLimit` to the sdk import and `UploadLimitReachedResponse, UploadRateLimitResponse` to the types import, then:

```ts
export type UploadRateLimit = UploadRateLimitResponse;

// The learner reached an upload limit (PRD §11): the API refused the presigned POST until rateLimit.retry_at.
export class UploadLimitError extends Error {
  constructor(readonly rateLimit: UploadRateLimit, message = "") {
    super(message);
    this.name = "UploadLimitError";
  }
}

// The caller's own limits, and which one is reached (null while uploads are open).
export async function loadUploadRateLimit(apiClient: Client = client): Promise<UploadRateLimit> {
  const { data, error, response } = await getUploadRateLimit({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /uploads/rate-limit failed (${response?.status ?? "no response"})`);
  return data;
}
```

In `uploadPdf`, after the `sessionOver` check:

```ts
  if (response?.status === 429) {
    const { detail, ...rateLimit } = error as UploadLimitReachedResponse;
    throw new UploadLimitError(rateLimit, detail);
  }
```

- [ ] **Step 5: `web/src/features/library/LibraryPage.tsx`.**
  - Imports: `Banner` from `../../components/Banner/Banner`; `limitTime` from `../../time`; `loadUploadRateLimit`, `UploadLimitError`, `type UploadRateLimit` from `../../api/documents`.
  - Prop `loadRateLimit?: () => Promise<UploadRateLimit>` with default `const defaultLoadRateLimit = () => loadUploadRateLimit();`.
  - State and refs:

    ```tsx
    const LIMIT_REASON = "Not uploaded. Upload limit reached.";
    // The caller's upload limit (PRD §11): while one is reached, Upload and the page drop are off until retry_at.
    const [rateLimit, setRateLimit] = useState<UploadRateLimit | null>(null);
    const limited = rateLimit?.limit != null && rateLimit.retry_at != null;
    const limitedRef = useRef(false); // files already queued in a batch read it, not the render's value
    useEffect(() => { limitedRef.current = limited; }, [limited]);
    const loadRateLimitRef = useRef(loadRateLimit);
    useEffect(() => { loadRateLimitRef.current = loadRateLimit; }, [loadRateLimit]);
    // A failed load leaves uploads open: the API still refuses past the limit.
    const refreshRateLimit = useCallback(async () => {
      try {
        const loaded = await loadRateLimitRef.current();
        if (alive.current) setRateLimit(loaded);
      } catch {
        // keep the last known state
      }
    }, []);
    useEffect(() => { void refreshRateLimit(); }, [refreshRateLimit]);
    // Open again when the limit ends, without a reload.
    useEffect(() => {
      if (!limited || !rateLimit?.retry_at) return;
      const wait = Math.max(0, new Date(rateLimit.retry_at).getTime() - Date.now());
      const timer = setTimeout(() => {
        setRateLimit((current) => (current ? { ...current, limit: null, retry_at: null } : current));
        void refreshRateLimit();
      }, wait);
      return () => clearTimeout(timer);
    }, [limited, rateLimit?.retry_at, refreshRateLimit]);
    ```

    (Declare these after `alive` is defined.)
  - A helper used by both checks:

    ```tsx
    function refuseForLimit(file: File, i: number, say: () => void) {
      setRejected((list) => [...list, { name: file.name, reason: LIMIT_REASON }]);
      parts.current[i] = `${file.name}: ${LIMIT_REASON}`;
      say();
    }
    ```
  - In `one()`, first line after `rejectionReason`'s block: `if (limitedRef.current) return refuseForLimit(file, i, say);`.
  - In `send()`, after `acquireSlot` resolved and before `check(file)`: if `limitedRef.current`, remove the tray row (`setTray((items) => items.filter((t) => t.id !== id))`) and `refuseForLimit(...)`, return. In the `catch` of the upload, before the generic failure:

    ```tsx
    } catch (error) {
      if (error instanceof UploadLimitError) {
        limitedRef.current = true;
        setRateLimit(error.rateLimit);
        setTray((items) => items.filter((t) => t.id !== id));
        refuseForLimit(file, i, say);
        return;
      }
      ...existing generic failure...
    ```
    (The `say()` / `refresh()` at the end of `send` are skipped by the early return; that's fine — nothing was created.)
  - In `addFiles`'s `finally`, after `inFlight.current--`: `if (inFlight.current === 0) void refreshRateLimit();` (the last upload of a batch can reach the limit).
  - Drop: `usePageDrop((files) => { if (!picking && !details && !limitedRef.current) void addFiles(files); })`, and render the overlay only when not limited: `{dragging && !picking && !details && !limited && <DropOverlay />}`.
  - Buttons: header Upload, all-archived Upload, and first-run "Choose PDFs" get `disabled={limited}` and `aria-describedby={limited ? "upload-limit" : undefined}`.
  - Banner, rendered right after the status `<p>`:

    ```tsx
    {limited && rateLimit?.retry_at && (
      <div id="upload-limit" className={styles.limit}>
        <Banner variant="attn" title="Upload limit reached.">
          <p>
            You can upload up to {rateLimit.per_hour} files per hour and {rateLimit.per_day} per day. You can upload again at {limitTime(new Date(rateLimit.retry_at))}.
          </p>
        </Banner>
      </div>
    )}
    ```

    Add `.limit { margin-block-end: var(--space-3); }` to `LibraryPage.module.css` (check `DESIGN.md` / neighboring rules for the spacing token actually used between the header and the toolbar and use that one).
  - Announce it: when the 429 arrives, the live region already reads `"<file>: Not uploaded. Upload limit reached."`; append the banner sentence once: in the `UploadLimitError` branch set `parts.current[i] = \`${file.name}: ${LIMIT_REASON} You can upload again at ${limitTime(new Date(error.rateLimit.retry_at!))}.\``.

- [ ] **Step 6: Run the web tests and build**

Run: `cd web && npm test && npm run build`
Expected: all pass.

- [ ] **Step 7: Look at it.** With the tests green, render the mockup state again (`npm run design:shots -- --states "library-rate-limited" --round v0.10 --theme both`) and compare against the built page's banner placement (under the page header, above the tabs). Differences from the mockup to keep: the mockup's second "If it's the daily limit…" line is a review variant — show only the limit hit; the Banner component's `attn` icon replaces the mockup's clock icon.

- [ ] **Step 8: Commit**

```bash
git add web
git commit -m "Show the upload limit in the Library and disable Upload until it ends" -m "Matches library-rate-limited@v0.10: the banner says when uploads open again in GMT+7, Upload and the page drop are off, and a batch stops at the first 429 (#66)."
```

---

## Self-Review Notes

- Spec coverage: 21st/hour and 101st/day → Task 1 (rule), Task 2 (service), Task 3 (HTTP 429 + retry-at). Duplicates/failed count → Task 2 test. Midnight GMT+7 with the fake clock → Tasks 1 and 2. Library message + disabled Upload/drop → Task 4. Isolation → Task 3 Step 2. SSM settings → Task 3 Step 6. Checks → each task.
- PRD: behavior already specified (US-2, US-9, §11, D27); no PRD change. The new endpoint is an API detail recorded in the knowledge README.
