# Processing turns the document ready: page text, chunks, embeddings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the worker stores a new content, it extracts page text with `pypdf`, saves it as `contents/<sha256>.pages.json`, chunks it per ADR 0008, embeds the chunks with Nova (1024 dims) into `chunks`, and turns the content and the learner's document **ready** with the subject "General". Unparseable PDFs and PDFs without a text layer end **failed** with a reason.

**Architecture:** `knowledge` gains a `Chunk` value, `Content.ready()/fail()`, `Document.ready(subject_ids)`, a `PdfExtractor` port (pypdf adapter), a `ChunkRepository` in the library unit of work, and `ObjectStore.put()`. `IngestionService.process_content()` runs after the store transaction commits (no row lock while calling Bedrock) and is re-run when SQS redelivers an upload whose document is still processing. The chunker is a LangChain `BaseDocumentTransformer` built by a registry in `knowledge.adapters` from settings; the service validates its output. The worker composes it all; Compose gives the worker real Bedrock credentials while S3/SQS keep LocalStack's dummy keys.

**Tech Stack:** pypdf 6, langchain-text-splitters (`RecursiveCharacterTextSplitter`), langchain-core `Embeddings` / `BaseDocumentTransformer`, `NovaEmbeddings` via `ModelFactory`, SQLAlchemy Core + pgvector (`pgvector.sqlalchemy.Vector`), Alembic, pytest; React (Library table).

**Spec:** GitHub issue #61 (slice of US-2 #9); PRD §9.2 (document processing path), §9.4, §9.5; ADR 0005, ADR 0008; mockup round v0.4 `StateBadge` *ready*/*failed*.

## Global Constraints

- Page text: `pypdf` plain mode, one entry per physical page; saved **raw** as JSON at `contents/<sha256>.pages.json` (`contents.text_key`), shape `{"pages": [{"page": 1, "text": "…"}, …]}`.
- Chunker: `RecursiveCharacterTextSplitter(separators=["\n\n", "\n", ". ", " ", ""], chunk_size=1000, chunk_overlap=200, length_function=len, is_separator_regex=False)`, run per page; values from settings `chunking.method = "recursive_character"`, `chunking.params = {"chunk_size": 1000, "chunk_overlap": 200}`. Chunker id recorded on the content: `recursive_character:1000/200:v1`.
- Cleanup before splitting (adapter): NFKC, join line-end hyphens between lowercase letters (`exam-\nple` → `example`), remove control characters except `\n` and `\t`.
- Service validation of every chunk: integer `metadata["page"]` ≥ 1, non-blank text, ≤ 8,192 characters; `seq` = output order starting at 0. Pages with only whitespace are not passed to the chunker.
- Failure reasons, verbatim: unparseable → `This file isn't a readable PDF`; no text layer (pages average < 50 non-whitespace characters, or zero pages) → `No text layer (scanned PDFs are not supported yet)`.
- Embeddings: `ModelFactory.embedding()` (Nova, `amazon.nova-2-multimodal-embeddings-v1:0`, 1024 dims); the content records `embedding_model` and `embedding_dim`; a vector of another length is an error (crash → redelivery → DLQ).
- General subject id: `00000000-0000-4000-8000-000000000001` (seeded by migration 0002).
- Crashes (S3, Bedrock, DB) are raised, not turned into failed states; SQS redelivers and the DLQ catches repeats. Retry is a later slice.
- Layering: `pypdf` and `langchain_text_splitters` only in `knowledge.adapters`; `knowledge.application` may use `langchain_core` and `subjects.application`.
- Unit tests use `fake_embeddings`, `FakeObjectStore`, and `FakePdfExtractor`; real Bedrock is never called in unit tests.
- Commits: imperative subject, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; web: `cd web && npm run build && npm test`.

## Review Focus

1. **SQS redelivers an upload whose processing crashed** (Bedrock throttled after the content was stored) — processing must run again, not be skipped as "already handled". Pinned in Task 3 (`test_redelivery_reprocesses_a_stored_content_that_is_still_processing`).
2. **Processing runs twice for one content** (redelivery after a crash between saving chunks and the message delete) — chunks are replaced, never duplicated (`seq` unique). Pinned in Task 3 (`test_processing_twice_keeps_one_set_of_chunks`) and Task 4 (`test_replace_chunks_is_idempotent`).
3. **A PDF with some blank pages** (figure-only or blank page in the middle) — blank pages make no chunks; other pages keep their physical page numbers. Pinned in Task 3 (`test_blank_pages_make_no_chunks_and_pages_keep_physical_numbers`).
4. **A non-PDF or truncated file renamed `.pdf`** — failed with "This file isn't a readable PDF", no chunks, no pages.json. Pinned in Task 2 (`test_garbage_bytes_raise_unreadable`) and Task 3 (`test_unreadable_pdf_fails_content_and_document`).
5. **A custom chunker returns a bad chunk** (no page, empty text, too long) — the service refuses it loudly instead of storing it. Pinned in Task 3 (`test_invalid_chunker_output_is_rejected`).

---

## File structure

```
backend/pyproject.toml                                         # dev group: pypdf, langchain-text-splitters
backend/src/smart_tutor/
  shared/config.py                                              # + ChunkingConfig, localstack flag
  shared/adapters/aws/clients.py                                # LocalStack dummy creds when settings.localstack
  shared/adapters/postgres/migrations/versions/0003_chunks.py
  subjects/domain/subject.py                                    # GENERAL_SUBJECT_ID
  subjects/application/__init__.py                              # re-export GENERAL_SUBJECT_ID, SubjectNames
  subjects/application/subject_names.py, subjects/ports/subject_repository.py, subjects/adapters/sql_subjects.py
  knowledge/domain/content.py                                   # pages_key, failure reasons, ready(), fail()
  knowledge/domain/chunk.py                                     # Chunk, validate_chunk
  knowledge/domain/document.py                                  # subject_ids, ready()
  knowledge/ports/pdf_extractor.py                              # PdfExtractor, UnreadablePdfError
  knowledge/ports/library.py                                    # ContentRepository.get/save, ChunkRepository, Document repo additions
  knowledge/ports/object_store.py                               # put()
  knowledge/application/ingestion_service.py                    # process_content(), ProcessingTools
  knowledge/adapters/pypdf_extractor.py, knowledge/adapters/chunking.py
  knowledge/adapters/sql_tables.py, sql_library.py, s3_object_store.py
  apps/worker/main.py                                           # compose extractor, chunker, embeddings
  apps/api/routes/knowledge.py                                  # subjects in DocumentResponse
backend/tests/fakes/{knowledge,pdfs}.py, unit/knowledge/*, integration/knowledge/*
compose.yaml, .env.example                                      # worker Bedrock credentials
web/src/features/library/DocumentTable.tsx (+ test), web/src/api/ (regenerated)
sdd/prd.md (v2.9), knowledge/README.md
```

---

### Task 1: Domain — Chunk, Content and Document state changes, General subject

**Files:**
- Create: `backend/src/smart_tutor/knowledge/domain/chunk.py`, `backend/src/smart_tutor/subjects/domain/subject.py`
- Modify: `knowledge/domain/content.py`, `knowledge/domain/document.py`, `knowledge/domain/errors.py`, `subjects/application/__init__.py`
- Test: `backend/tests/unit/knowledge/test_domain.py`

**Interfaces — Produces:**
- `content.pages_key(sha256) -> str` = `contents/<sha256>.pages.json`; constants `UNREADABLE_PDF = "This file isn't a readable PDF"`, `NO_TEXT_LAYER = "No text layer (scanned PDFs are not supported yet)"`, `MIN_AVERAGE_CHARS = 50`, `has_text_layer(pages: list[str]) -> bool`.
- `Content` new fields (defaults `None`): `failure_reason`, `pages: int | None`, `text_key`, `chunker`, `embedding_model`, `embedding_dim`. Methods `ready(*, pages, text_key, chunker, embedding_model, embedding_dim)` and `fail(reason)`; both raise `ContentStateError` unless `PROCESSING`.
- `chunk.MAX_CHUNK_CHARS = 8192`; `@dataclass(frozen=True) Chunk(content_id, seq: int, page: int | None, text: str, embedding: list[float])`; `validate_chunk(page: object, text: str) -> int` returns the page or raises `InvalidChunkError`.
- `Document.subject_ids: list[SubjectId]` (default empty); `Document.ready(subject_ids)` — requires `PROCESSING` and a linked content, 1–3 distinct ids → `READY` (interim until US-2b's `awaiting_subjects`).
- `subjects.application.GENERAL_SUBJECT_ID: SubjectId`.

- [ ] Step 1: Write failing tests: `has_text_layer(["x"*49])` false, `["x"*60, ""]` false (avg 30), `["x"*100]` true, `[]` false; whitespace doesn't count. `Content.ready` sets all fields and state; `ready`/`fail` on a ready content raise `ContentStateError`. `validate_chunk` accepts `(3, "text")`, rejects `None`, `"3"`, `True`, `0`, blank text, 8,193 chars. `Document.ready([GENERAL])` from processing with content → ready; without content, with 0 or 4 subjects, duplicates, or from failed → `DocumentStateError`.
- [ ] Step 2: Run `uv run pytest tests/unit/knowledge/test_domain.py -q` — fails.
- [ ] Step 3: Implement. `has_text_layer`: `bool(pages) and sum(len("".join(p.split())) for p in pages) / len(pages) >= MIN_AVERAGE_CHARS`. Bools are not pages (`isinstance(page, bool)` check first).
- [ ] Step 4: Tests pass; commit "Add chunk, ready, and failed rules to the knowledge domain".

### Task 2: Adapters — pypdf extractor and the chunker registry

**Files:**
- Modify: `backend/pyproject.toml` (dev group gets `pypdf>=6.0`, `langchain-text-splitters>=1.1` so tests and mypy see the adapters; images still use `--no-dev`), `uv.lock`, `shared/config.py` (`ChunkingConfig(method="recursive_character", params={"chunk_size": 1000, "chunk_overlap": 200})`, `Settings.chunking`)
- Create: `knowledge/ports/pdf_extractor.py`, `knowledge/adapters/pypdf_extractor.py`, `knowledge/adapters/chunking.py`, `backend/tests/fakes/pdfs.py`
- Test: `backend/tests/unit/knowledge/test_pypdf_extractor.py`, `backend/tests/unit/knowledge/test_chunking.py`

**Interfaces — Produces:**
- Port: `class UnreadablePdfError(Exception)`; `class PdfExtractor(ABC): extract_pages(data: bytes) -> list[str]` (raw text, index = page − 1; raises `UnreadablePdfError`).
- `PypdfExtractor(PdfExtractor)`: `PdfReader(BytesIO(data))`, `page.extract_text()` (plain mode) or `""`; any `pypdf.errors.PyPdfError`, `ValueError`, or encrypted file → `UnreadablePdfError`.
- `chunking.build_chunker(config: ChunkingConfig) -> tuple[BaseDocumentTransformer, str]`; unknown method → `ValueError`. `recursive_character` returns `CleanedSplitter` (a `BaseDocumentTransformer` that applies `clean_page_text` then splits with the ADR 0008 splitter, keeping metadata) and id `f"recursive_character:{size}/{overlap}:v1"`. `clean_page_text(text) -> str`.
- `fakes.pdfs.make_pdf(pages: list[str]) -> bytes`: a valid one-font (Helvetica) PDF, one `Tj` line per text line, correct xref.

- [ ] Step 1: Failing tests: `PypdfExtractor().extract_pages(make_pdf(["Hello page one", "", "Page three"]))` → 3 entries, texts contain the words, middle blank; `b"not a pdf"` and a truncated `make_pdf(...)[:40]` raise `UnreadablePdfError`. `clean_page_text("ﬁne exam-\nple\x07 A-\nB")` → `"fine example A-\nB"`. A 2,500-char page gives chunks all ≤ 1,000 chars with `metadata["page"]` kept; id is `recursive_character:1000/200:v1`; unknown method raises.
- [ ] Step 2: Run them — fail.
- [ ] Step 3: Implement; `uv lock`; `uv sync`.
- [ ] Step 4: Tests pass; `PYTHONUTF8=1 uv run lint-imports` passes; commit "Read page text with pypdf and chunk it per ADR 0008".

### Task 3: IngestionService.process_content

**Files:**
- Modify: `knowledge/ports/library.py`, `knowledge/ports/object_store.py`, `knowledge/application/ingestion_service.py`, `knowledge/application/__init__.py`, `tests/fakes/knowledge.py`, `tests/fakes/__init__.py`, `tests/unit/knowledge/test_ingestion_service.py`, `tests/unit/apps/worker/test_worker.py`
- Test: `tests/unit/knowledge/test_processing.py`

**Interfaces:**
- Consumes: Task 1 domain, Task 2 `PdfExtractor`, `UnreadablePdfError`.
- Produces (ports): `ContentRepository.get(content_id) -> Content | None`, `get_for_update(content_id) -> Content | None`, `save(content)`; `DocumentRepository.list_processing_for_content_for_update(content_id) -> list[Document]`; `DocumentRepository.save` also replaces the document's subject rows; `ChunkRepository.replace(content_id, chunks: list[Chunk])`; `LibraryUnitOfWork.chunks`; `ObjectStore.put(key, data: bytes, content_type: str)`.
- Produces (application): `@dataclass(frozen=True) ProcessingTools(extractor: PdfExtractor, chunker: BaseDocumentTransformer, chunker_id: str, embeddings: Embeddings, embedding_model: str, embedding_dim: int)`; `IngestionService(uow, objects, tools, new_id=new_uuid)`; `process_content(content_id) -> ContentState | None`. `ingest_upload` calls `process_content` after a STORED commit, and when the document is processing with a content already linked (redelivery).
- Fakes: `FakePdfExtractor` (bytes must start with `%PDF`; the rest decoded as UTF-8 and split on `\f` into pages; otherwise `UnreadablePdfError`); `PageChunker(BaseDocumentTransformer)` that splits each page into 100-char pieces keeping metadata (fakes stay free of pypdf and splitters); `fake_tools(dim=8, extractor=None, chunker=None, embeddings=None) -> ProcessingTools` with chunker id `"fake:100:v1"` and `fake_embeddings(dim)`, model name `"fake-embedding"`. In-memory chunks stored in `_State.chunks: dict[str, list[Chunk]]`, `_State.document_subjects` via `Document.subject_ids`.

Flow of `process_content` (no lock held during extraction and embedding):
1. Read the content; return None unless `PROCESSING`.
2. Read `content.s3_key`; extract pages. `UnreadablePdfError` → fail with `UNREADABLE_PDF`. `not has_text_layer(pages)` → fail with `NO_TEXT_LAYER`.
3. `put(pages_key(sha), json.dumps({"pages": [{"page": i+1, "text": t}]}), "application/json")`.
4. `chunker.transform_documents([Document(page_content=t, metadata={"page": i+1}) for non-blank pages])`; `validate_chunk` each; `embed_documents(texts)`; every vector must have `embedding_dim` floats (else `ValueError`).
5. One transaction: `get_for_update`; if no longer processing, return None; `chunks.replace`; `content.ready(...)`; each processing document of the content → `ready([GENERAL_SUBJECT_ID])`; save; commit. Return `READY`.
Fail path: one transaction: `get_for_update`, `content.fail(reason)`, each processing document `.fail(reason)`, save, commit; no chunks; return `FAILED`.

- [ ] Step 1: Failing tests in `test_processing.py`: happy path (chunks in seq order 0..n with page numbers, pages.json raw content, content fields incl. `chunker` = fake id and `embedding_dim`, document ready with `[GENERAL_SUBJECT_ID]`); `test_blank_pages_make_no_chunks_and_pages_keep_physical_numbers`; `test_unreadable_pdf_fails_content_and_document`; `test_pdf_without_text_layer_fails`; `test_processing_twice_keeps_one_set_of_chunks`; `test_redelivery_reprocesses_a_stored_content_that_is_still_processing` (first embed raises, second delivery succeeds); `test_invalid_chunker_output_is_rejected`; `test_wrong_embedding_dimension_crashes_and_stores_nothing`. Update existing ingestion and worker tests to build services with fake tools and longer PDF text (≥ 50 non-whitespace chars per page); a stored document now ends ready.
- [ ] Step 2: Run — fail.
- [ ] Step 3: Implement ports, fakes, service.
- [ ] Step 4: `uv run pytest` passes; mypy and lint-imports pass; commit "Process stored contents into chunks and make documents ready".

### Task 4: SQL and S3 adapters, migration 0003

**Files:**
- Create: `shared/adapters/postgres/migrations/versions/0003_chunks.py`
- Modify: `knowledge/adapters/sql_tables.py`, `sql_library.py`, `s3_object_store.py`
- Test: `tests/integration/knowledge/test_sql_library.py`, `tests/integration/knowledge/test_s3_object_store.py`, `tests/integration/shared/test_migrations.py` (if it lists tables)

Migration 0003: `create extension if not exists vector`; `contents` add `text_key text`, `chunker text`, `embedding_model text`, `embedding_dim integer`; table `chunks(chunk_id uuid pk, content_id uuid not null fk contents, seq integer not null, page integer null, text text not null, embedding vector(1024) not null, unique(content_id, seq) name chunks_content_seq, check(page is null or page >= 1))`; index `chunks_embedding_hnsw using hnsw (embedding vector_cosine_ops)`; downgrade drops them.

Adapters: `chunks` Table with `pgvector.sqlalchemy.Vector(1024)`; `_Chunks.replace` = delete where content_id, then bulk insert with new uuids; `_Contents.get/get_for_update/save` (save writes state, failure_reason, pages, text_key, chunker, embedding_model, embedding_dim); `_document` loads `subject_ids` from `document_subjects` (ordered); `_Documents.save` deletes and re-inserts subject rows; `list_processing_for_content_for_update`. `S3ObjectStore.put` = `put_object(Bucket, Key, Body, ContentType)`.

- [ ] Step 1: Failing integration tests (Compose Postgres): `test_replace_chunks_is_idempotent` (two replaces → one set, ordered by seq, vectors round-trip); content ready fields round-trip; document ready with General round-trips `subject_ids`; S3 `put` then `read`.
- [ ] Step 2: Run `uv run pytest -m integration tests/integration/knowledge -q` against a database migrated with 0003 — fails before implementation.
- [ ] Step 3: Implement.
- [ ] Step 4: Integration and unit tests pass; commit "Store chunks in pgvector and page text in S3".

### Task 5: Worker composition and Compose credentials

**Files:**
- Modify: `apps/worker/main.py`, `shared/config.py` (`localstack: bool = False` — S3/SQS use LocalStack's dummy keys), `shared/adapters/aws/clients.py`, `compose.yaml`, `.env.example`, `backend/tests/unit/shared/test_config.py` (or a clients test)
- Test: `tests/unit/shared/test_aws_clients.py`

Worker: `extractor = PypdfExtractor()`, `chunker, chunker_id = build_chunker(settings.chunking)`, `embeddings = ModelFactory(settings).embedding()`, `ProcessingTools(..., embedding_model=settings.models.embedding.model_id, embedding_dim=int(settings.models.embedding.params["dimensions"]))`.

Compose worker: drop the `localstack-aws` anchor; `SMART_TUTOR_LOCALSTACK: "true"`; mount `~/.aws:/aws:ro`; `AWS_CONFIG_FILE: /aws/config`, `AWS_SHARED_CREDENTIALS_FILE: /aws/credentials`; `AWS_PROFILE` comes from `.env`. Clients: when `settings.localstack`, pass `aws_access_key_id="test", aws_secret_access_key="test"` to S3 and SQS clients so your real keys never go to LocalStack; Bedrock uses the profile.

- [ ] Step 1: Failing test: with `Settings(localstack=True)`, `s3_client(...)._request_signer._credentials.access_key == "test"`; default settings don't force keys.
- [ ] Step 2–3: Implement; `docker compose config` shows the worker mount.
- [ ] Step 4: Checks pass; commit "Give the worker Bedrock credentials and compose the processing pipeline".

### Task 6: Show subjects in the Library

**Files:**
- Create: `subjects/ports/subject_repository.py`, `subjects/adapters/sql_subjects.py`, `subjects/application/subject_names.py`
- Modify: `subjects/application/__init__.py`, `knowledge/application/document_service.py` (`DocumentView.subject_ids`), `apps/api/routes/knowledge.py` + `services.py`/`deps.py` (`DocumentResponse.subjects: list[SubjectResponse(subject_id, name)]`), `web/src/api/` (regenerate with `make api-client`), `web/src/features/library/DocumentTable.tsx` + test
- Test: `tests/unit/subjects/test_subject_names.py`, `tests/unit/apps/api/test_knowledge_routes.py`, `tests/integration/subjects/test_sql_subjects.py`, `tests/isolation/test_documents.py` (subject ids only from own documents)

`SubjectNames(repo).names_for(user_id, subject_ids) -> dict[SubjectId, str]` — canonical names now (personal names arrive with US-10b; resolution order documented). The API route orchestrates: list documents (knowledge) → resolve names (subjects). Table: Subjects cell shows names joined by ", " or "Not chosen yet" when empty.

- [ ] Steps: failing tests → implement → `make api-client` → `cd web && npm run build && npm test` → commit "Show a document's subjects in the Library".

### Task 7: Docs and end-to-end check

- Modify: `sdd/prd.md` (status line v2.9; §9.4 Content row notes `text_key` holds the pages.json key; §9.5 notes the interim `processing → ready` with "General" until US-2b), `knowledge/README.md` (process_content, reasons), `subjects/README.md` (GENERAL_SUBJECT_ID, SubjectNames).
- End-to-end: migrate the Compose database, run the worker, upload an arXiv PDF through the API (`learner@example.com`), confirm *ready*, chunks ordered with pages, `contents/<sha>.pages.json` in LocalStack, `document_subjects` = General; upload a garbage `.pdf` and a text-less PDF → *failed* with reasons and no chunks.
- Commit "Document processing to ready in the PRD and module READMEs".
