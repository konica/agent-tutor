# `accounts` module (Release 1)

**Owns** (US-9, §9.4): upload limits, token usage (chat, document processing, background), rate-limit policy. The learner profile (time zone for reports) arrives in Release 3; Release 1 has no terms of use step (PRD Q45).

**Key classes:** `UploadLimits` (`per_hour`, `per_day`; `check(created, now, tz)` returns an `UploadBlock` (`window` hour or day, `retry_at`) or None; `since(now, tz)`), `UploadLimitReachedError`, `limit_time_label`; loader `load_upload_limits` (SSM `max-uploads-per-hour`, `max-uploads-per-day`). Service `UsageService` (token usage) arrives with US-9. Release 3 adds `Learner` and `LearnerService`.

**May use (application layer only):** none. Everyone may use `shared`.

**Rules:** Limits come from configuration (SSM), not code. No enrollment: a learner's subjects come from their documents (`knowledge`). The hour is rolling (an upload counts while `created_at > now − 1 h`); the day runs midnight to midnight in the app time zone (D27). When both are reached, the one that ends later is reported (a tie reports the day). `knowledge` counts the learner's `uploads` rows and asks `UploadLimits.check` before presigning.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `accounts.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
