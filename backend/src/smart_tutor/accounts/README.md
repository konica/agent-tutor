# `accounts` module (Release 1)

**Owns** (US-2, US-9, §9.4 learner profile): Learners (time zone), subject enrollments, token usage, rate-limit policy.

**Key classes:** `Learner`, `Enrollment`; services `EnrollmentService`, `UsageService`.

**May use (application layer only):** none. Everyone may use `shared`.

**Rules:** Enrollments live in PostgreSQL, not in token claims.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `accounts.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
