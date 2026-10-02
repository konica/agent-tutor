# `reports` module (Release 2)

**Owns** (US-15, §9.8): Daily and weekly reports across subjects (scheduled and on demand).

**Key classes:** `Report`; service `ReportService`.

**May use (application layer only):** `learning`, `quizzes`, `recommendations`. Everyone may use `shared`.

**Rules:** No report for a period without activity.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `reports.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
