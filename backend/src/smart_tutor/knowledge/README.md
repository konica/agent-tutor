# `knowledge` module (Release 1)

**Owns** (§9.5, US-10): Documents, versions and archiving, chunks, PDF ingestion, and semantic search.

**Key classes:** `Document`, `Chunk`; services `IngestionService`, `SearchService`; ports `PdfExtractor`, `DocumentStore`, `ChunkRepository`.

**May use (application layer only):** `accounts` (enrolled subjects for the search filter). Everyone may use `shared`.

**Rules:** Docling is imported only in `knowledge.adapters`. Search never returns `archived` chunks; `get_chunk` may.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `knowledge.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
