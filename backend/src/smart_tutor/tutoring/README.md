# `tutoring` module (Release 1)

**Owns** (PRD §9.2, US-3, US-3b, US-4 to US-6, US-13): Threads (1–3 subjects, grow to at most 3 with notices and a warning at the maximum), subject detection, relevance gate, growth check, the ask path, conversation management.

**Key classes:** `Thread` (`add_subject()` refuses beyond 3, never removes), `DetectionPolicy`, `RelevanceGate`, `GrowthPolicy`; services `SubjectDetector`, `AskService`, `ConversationService`; ports `Retriever`, `ThreadRepository`.

**May use (application layer only):** `knowledge` (the learner's subjects from their documents), `subjects` (names), `accounts`, `insights` (log declines). Everyone may use `shared`.

**Rules:** Never reads chunk tables: retrieval goes through the `Retriever` port (MCP client adapter). Threads store `subject_ids`, so renames never affect them. Document text is passed to the model as quoted data. Never imports `learning`.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `tutoring.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
