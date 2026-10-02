# `knowledge` module (Release 1)

**Owns** (§9.4, §9.5, US-2, US-2b, US-10, US-10b, US-11): The learner's library: contents deduplicated by SHA-256, documents (library entries), the single `can_read` access rule, upload, ingestion, metadata, chunks, search, and the shared subject catalog with personal names.

**Key classes:** `Content`, `Document` (`can_be_read_by()`), `Subject`, `PersonalSubjectName`, `Chunk`; services `UploadService`, `DeduplicationService`, `IngestionService`, `SubjectSuggester`, `SubjectCatalogService`, `DocumentService`, `SearchService`; ports `PdfExtractor`, `ObjectStore`, `ContentRepository`, `DocumentRepository`, `SubjectRepository`, `ChunkRepository`.

**May use (application layer only):** `accounts` (upload limits, document-processing usage). Everyone may use `shared`.

**Rules:** Docling is imported only in `knowledge.adapters`. Existing content is linked only after a server-computed SHA-256 of uploaded bytes, never on a browser hash (PRD D19). Every read goes through `can_read`. Other tables store `subject_id`, never a subject name. Search never returns chunks of archived documents.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `knowledge.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
