# `learning` module (Release 1)

**Owns** (§9.4, US-7, US-8, US-13b): Lesson Notes (one per thread, soft delete) and lifetime learning records (note trigger and idle trigger).

**Key classes:** `LessonNote` (`archive()`, `restore()`), `LearningRecord`; services `NoteService`, `LearningRecordService`; ports `NoteRepository`, `LearningMemory`.

**May use (application layer only):** `tutoring` (thread content, idle threads). Everyone may use `shared`.

**Rules:** No hard delete of notes. Records are written only by the two triggers, never per chat turn.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `learning.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
