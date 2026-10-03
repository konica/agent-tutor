# 0004. Split the subject catalog out of `knowledge` into a `subjects` module

- Status: accepted
- Date: 2026-10-03

## Context

After PRD v2, `knowledge` owned three concerns: the library (contents, documents, dedupe, states, `can_read`, upload, ingestion), search, and the shared subject catalog. The catalog has its own tables (`subjects`, `user_subject_names`) and rules (normalization, near-duplicate reuse, name checks, personal names), and other modules need subject names without depending on the library.

## Decision

- New Release 1 module **`subjects`**: catalog, personal names, suggestion ranking, name checks.
- `knowledge` keeps the library, ingestion, and search, and uses `subjects.application` for suggestions and get-or-create.
- `tutoring` uses `subjects.application` for names and `knowledge.application` for the learner's subjects.
- Module order: `… tutoring → graph → knowledge → subjects → accounts | insights`.

## Consequences

- One more module and privacy contract (18 contracts).
- Done before M1 code exists, so the split cost only documentation and contracts.
