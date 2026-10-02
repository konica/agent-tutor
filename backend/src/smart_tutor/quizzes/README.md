# `quizzes` module (Release 2)

**Owns** (US-14): Multiple-choice quizzes generated from selected notes, graded in code.

**Key classes:** `Quiz` (`grade(answers)`); service `QuizService`.

**May use (application layer only):** `learning`. Everyone may use `shared`.

**Rules:** The answer key is never exposed to the client before submission.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `quizzes.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
