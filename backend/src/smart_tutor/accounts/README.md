# `accounts` module (Release 1)

**Owns** (US-9, §9.4 learner profile): Learner profile (time zone), upload limits, token usage (chat, document processing, background), rate-limit policy.

**Key classes:** `Learner`, `UploadLimits`; services `LearnerService`, `UsageService`.

**May use (application layer only):** none. Everyone may use `shared`.

**Rules:** Limits come from configuration (SSM), not code. No enrollment: a learner's subjects come from their documents (`knowledge`).

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `accounts.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
