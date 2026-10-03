# `recommendations` module (Release 3)

**Owns** (US-16, §9.2 recommend path): "What should I learn next?" recommendations.

**Key classes:** `Recommendation`; service `RecommendationService`.

**May use (application layer only):** `catalog`, `quizzes`, `learning`. Everyone may use `shared`.

**Rules:** Candidates come from code; the model only ranks. Topics outside the candidate list are rejected.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `recommendations.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
