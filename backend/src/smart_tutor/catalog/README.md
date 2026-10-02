# `catalog` module (Release 2)

**Owns** (§9.7): Topic catalog per content, derived from Docling headings at ingestion; a learner's catalog is the union over their active documents.

**Key classes:** `TopicEntry`; service `CatalogService`.

**May use (application layer only):** `knowledge`. Everyone may use `shared`.

**Rules:** Topics of archived documents are never offered for recommendations.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `catalog.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
