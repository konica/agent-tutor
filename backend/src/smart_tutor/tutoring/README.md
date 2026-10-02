# `tutoring` module (Release 1)

**Owns** (§9.2, US-3 to US-6, US-13): Threads, subject detection and binding, relevance gate, the ask path, conversation management.

**Key classes:** `Thread` (`bind_subject()` refuses to rebind), `DetectionPolicy`, `RelevanceGate`; services `SubjectDetector`, `AskService`, `ConversationService`; ports `Retriever`, `ThreadRepository`.

**May use (application layer only):** `knowledge` (the learner's subjects and their names), `accounts`, `insights` (log declines). Everyone may use `shared`.

**Rules:** Never reads chunk tables: retrieval goes through the `Retriever` port (MCP client adapter). Threads store `subject_id`, so renames never affect them. Document text is passed to the model as quoted data. Never imports `learning`.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `tutoring.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
