# `accounts` module (Release 1)

**Owns** (US-9, §9.4): upload limits, token usage (chat, document processing, background), rate-limit policy. The learner profile (time zone for reports) arrives in Release 3; Release 1 has no terms of use step (PRD Q45).

**Key classes:** `UploadLimits`; service `UsageService`. Release 3 adds `Learner` and `LearnerService`.

**May use (application layer only):** none. Everyone may use `shared`.

**Rules:** Limits come from configuration (SSM), not code. No enrollment: a learner's subjects come from their documents (`knowledge`).

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `accounts.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
