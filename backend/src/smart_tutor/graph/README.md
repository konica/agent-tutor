# `graph` module (Release 2, extended in Release 5)

**Owns** (PRD §9.7, §9.16, US-19, US-20, US-18): the research map — works (contents grouped by `work_key`), citation links from saved references, per-subject timeline, reading order, reading paths; in Release 5 also model-labeled relationships with evidence and concept history.

**Key classes:** `Work`, `WorkLink`, `ReadingOrder`; service `ResearchMapService`.

**May use (application layer only):** `knowledge`. Everyone may use `shared`.

**Rules:** A learner's map includes only works they can read (`can_read`). Links are computed once per content and shared, like embeddings. Links, timeline, and reading order use no model calls.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `graph.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
