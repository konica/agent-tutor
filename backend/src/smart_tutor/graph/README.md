# `graph` module (Release 3)

**Owns** (§9.16, US-18): Knowledge graph: citation links between contents, relationship labels with evidence, per-subject timeline, concept history.

**Key classes:** `Relationship`, `Timeline`; service `GraphService`.

**May use (application layer only):** `knowledge`. Everyone may use `shared`.

**Rules:** A learner's graph includes only contents they can read (`can_read`). Edges are computed once per content pair and shared, like embeddings.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `graph.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
