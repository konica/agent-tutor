# `subjects` module (Release 1)

**Owns** (PRD §9.4, D1, D20, D21, US-2b, US-10b): The shared subject catalog (stable `subject_id`, canonical name, name embedding), personal subject names (rename, reset), ranking subject suggestions for a learner, and subject-name checks (normalization, near-duplicate reuse, personal-data/offensive check).

**Key classes:** `Subject`, `SubjectName` (normalization), `PersonalSubjectName`; services `SubjectCatalogService` (get-or-create by normalized name, resolve names for a learner), `SubjectSuggester` (rank 3 suggestions from a summary embedding, the learner's subjects, and proposed names), `SubjectNameChecker`; ports `SubjectRepository`, `PersonalNameRepository`.

**Present now:** `GENERAL_SUBJECT_ID` (the "General" subject, seeded by migration 0002; the interim subject of every ready document until US-2b); `SubjectNames` (application: resolves canonical names now, personal names later); port `SubjectRepository` with the SQL adapter `sql_subjects`.

**May use (application layer only):** none (uses `shared` model ports for embeddings and the name check). Everyone may use `shared`.

**Rules:** `subject_id` never changes and is never reused; there is no admin rename, merge, or hide. Personal names are per learner, unique among that learner's subjects, and never shown to others. No creator is stored in the shared view. Other modules store only `subject_id`s and ask this module for names at read time.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `subjects.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
