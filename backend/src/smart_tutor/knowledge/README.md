# `knowledge` module (Release 1)

**Owns** (PRD §9.2 document processing, §9.3, §9.4, §9.5, US-2, US-2b, US-10, US-11): The learner's library: contents deduplicated by SHA-256 (state machine, shared retry), documents (library entries with 1–3 subjects, state, archive flag, visibility, grants), the single `can_read` access rule, upload, ingestion (first-pages step, page text with `pypdf` and saved output, work key), chunks, and search.

**Key classes:** `Content` (states, `retry()`), `Document` (states, `set_subjects()` 1–3, `archive()`, `restore()`, `can_be_read_by()`), `Chunk`; services `UploadService`, `DeduplicationService`, `IngestionService`, `DocumentService`, `SearchService`; ports `PdfExtractor`, `FirstPagesReader`, `ObjectStore`, `ContentRepository`, `DocumentRepository`, `ChunkRepository`.

**May use (application layer only):** `subjects` (suggestions, get-or-create subjects, names), `accounts` (rate limits, document-processing usage). Everyone may use `shared`.

**Rules:** The PDF loader is imported only in `knowledge.adapters` (ADR 0005). Existing content is linked only after a server-computed SHA-256 of uploaded bytes, never on a browser hash (PRD D19). Every read goes through `can_read`. Documents store `subject_id`s only. Search returns chunks only from ready, non-archived documents. Upload keys are `uploads/<user_id>/<upload_id>.pdf`; the worker hashes the bytes and stores new contents at `contents/<sha256>.pdf`. Until US-11, a known hash fails the document with "Duplicate uploads aren't supported yet".

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `knowledge.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
