# Per-learner contents (#120) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each learner's upload becomes their own content (unique `(owner_id, sha256)`); a learner's own duplicate removes the placeholder document and points the upload to the existing document, which the web tray shows as "Already in your library". The Glacier tagger is removed.

**Architecture:** `contents` gains `owner_id` and loses `processed_by_user_id`; the worker's insert-or-get is keyed by owner. `uploads` gains `document_id` (the document the upload ended in). A new `GET /uploads/{upload_id}` lets the browser learn the outcome; the Library polls it after each upload and turns the tray row into "Already in your library" on `duplicate`.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / Alembic / Postgres; React + TypeScript + Vitest; Helm; AWS CDK.

**Spec:** GitHub issue #120; `sdd/prd.md` v2.23 §8 US-11, D18, D19, §9.2 steps 2–3, §9.4 Content/Upload, §9.5; `sdd/adr/0011-*.md`. Design state `library-already-in-library@v0.10` (tag `design-v0.10`).

## Global Constraints

- New content keys: `contents/<owner_id>/<content_id>.pdf` and `contents/<owner_id>/<content_id>.pages.json`. Existing rows keep their `s3_key` / `text_key`.
- Another learner's content is never looked up by hash (D18, D19). No API response may reveal another learner's upload or document.
- Copy (exact): "Already in your library", "Already in your library, archived", link text "Open document".
- Remove `DUPLICATE_UPLOAD` and the text "Duplicate uploads aren't supported yet" from code and tests.
- Restore is out of scope: it needs #108 (archive/restore, not built). The API reports `archived`; the tray shows "Already in your library, archived" without a Restore button until #108.
- Checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; web `npm run build` and `npx vitest run`; `cd infra && uv run pytest`; `helm lint deploy/helm/smart-tutor`.
- Commits: imperative subject, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Redelivery of an upload whose duplicate was already handled (placeholder document gone): the worker must delete the leftover upload object and do nothing else — Task 1 test `test_redelivery_after_a_duplicate_deletes_the_leftover_upload`.
2. Two learners, same bytes: two contents, two chunk sets, both reach `awaiting_subjects`; neither learner's `GET /uploads/{id}` / `GET /documents` shows the other's — Task 1 unit test + Task 3 isolation test.
3. Learner B asks for learner A's `upload_id` → 404, identical to an unknown id — Task 3 isolation test.
4. Migration on existing data: contents get `owner_id` from their document (else `processed_by_user_id`); old "Duplicate uploads aren't supported yet" placeholder documents are removed — Task 2 integration test.
5. Upload status polling stops on `stored`/`duplicate`, on session expiry, and on unmount; transient errors keep polling — Task 4 tests.

---

### Task 1: Domain, ports, fakes, and the worker's per-learner insert-or-get

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/content.py`, `domain/upload.py`, `domain/document.py`
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py`
- Modify: `backend/src/smart_tutor/knowledge/application/ingestion_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/upload_service.py`, `application/__init__.py` (export `UploadStatus`)
- Modify: `backend/tests/fakes/knowledge.py`, `backend/tests/fakes/ingest.py`
- Modify tests: `backend/tests/unit/knowledge/test_domain.py`, `test_ingestion_service.py`, `test_processing.py`, `test_retry_service.py`, `test_description.py`, any other unit test using `processed_by_user_id`, `content_key(sha)` or `pages_key(sha)`
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_tables.py`, `adapters/sql_library.py` — apply Task 2 Step 2 (adapter code) in this task so `mypy` stays green; Task 2 adds the migration and the integration tests.

**Interfaces (Produces):**
- `content_key(owner_id: UserId, content_id: ContentId) -> str` → `f"contents/{owner_id}/{content_id}.pdf"`
- `pages_key(owner_id: UserId, content_id: ContentId) -> str` → `f"contents/{owner_id}/{content_id}.pages.json"`
- `Content.owner_id: UserId` (replaces `processed_by_user_id`, same position); `Content.first_upload(content_id, sha256, size, owner_id)` (same argument order as before), `s3_key = content_key(owner_id, content_id)`.
- `Upload.document_id: DocumentId | None = None` (the document the upload ended in).
- `UploadOutcome.STORED` comment: "new content stored at contents/<owner_id>/<content_id>.pdf"; `DUPLICATE`: "the learner already has these bytes; the upload points to their document".
- `ContentRepository.insert_or_get(content)` docstring: unique `(owner_id, sha256)`; concurrent callers with the same owner and hash get one row.
- `DocumentRepository.get_by_content(content_id: ContentId) -> Document | None` — the document linked to this content (one per content: contents are per owner). No access check.
- `DocumentRepository.remove(document_id: DocumentId) -> None` — delete a document row and its subject rows.
- `UploadRepository.record_outcome(upload_id, size, outcome, document_id: DocumentId) -> None`
- `UploadRepository.get(upload_id: UploadId) -> Upload | None`
- `knowledge.application.UploadStatus` (frozen dataclass: `outcome: UploadOutcome | None`, `document_id: DocumentId | None`, `archived: bool`) and `UploadService.upload_status(user_id: UserId, upload_id: UploadId) -> UploadStatus | None` (None when the upload doesn't exist or isn't the caller's).

- [ ] **Step 1: Update domain tests first.** In `test_domain.py`: the first-upload test asserts `content.s3_key == content_key(UserId("ada"), ContentId("c1")) == "contents/ada/c1.pdf"` and `content.owner_id == "ada"`; `pages_key(UserId("ada"), ContentId("c1")) == "contents/ada/c1.pages.json"`; delete the `DUPLICATE_UPLOAD` test (line ~84) and replace the `"Duplicate uploads aren't supported yet"` reason at ~316 with `"This file isn't a readable PDF"`.

- [ ] **Step 2: Rewrite ingestion tests** in `test_ingestion_service.py` (replace the duplicate tests; keep the rest, adjusting keys):

```python
def key(user: str, content_id: str, suffix: str = "pdf") -> str:
    return f"contents/{user}/{content_id}.{suffix}"


def test_a_new_file_is_stored_under_its_owner_and_the_upload_copy_removed() -> None:
    w = World()
    a = w.upload("ada")
    assert w.ingestion.ingest_upload(a.fields["key"]) is UploadOutcome.STORED
    [content] = w.library.state.contents.values()
    assert set(w.objects.objects) == {key("ada", content.content_id), key("ada", content.content_id, "pages.json")}
    assert w.objects.objects[key("ada", content.content_id)] == PDF
    assert (content.sha256, content.size, content.state, content.owner_id) == (SHA, len(PDF), "ready", "ada")
    doc = w.doc(a)
    assert (doc.content_id, doc.state) == (content.content_id, "awaiting_subjects")
    upload = w.library.state.uploads[a.upload_id]
    assert (upload.size, upload.outcome, upload.document_id) == (len(PDF), UploadOutcome.STORED, a.document_id)


def test_another_learners_identical_file_is_their_own_content() -> None:
    w = World()
    a, b = w.upload("ada"), w.upload("bob")
    w.ingestion.ingest_upload(a.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is UploadOutcome.STORED
    contents = sorted(w.library.state.contents.values(), key=lambda c: c.owner_id)
    assert [(c.owner_id, c.sha256, c.state) for c in contents] == [("ada", SHA, "ready"), ("bob", SHA, "ready")]
    assert contents[0].content_id != contents[1].content_id
    assert all(w.library.state.chunks[c.content_id] for c in contents)  # each embedded in full
    assert (w.doc(a).state, w.doc(b).state) == ("awaiting_subjects", "awaiting_subjects")
    assert w.doc(b).content_id == contents[1].content_id


def test_the_same_learners_duplicate_points_to_their_document() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada", name="copy.pdf")
    w.ingestion.ingest_upload(first.fields["key"])
    chunks_before = dict(w.library.state.chunks)
    assert w.ingestion.ingest_upload(second.fields["key"]) is UploadOutcome.DUPLICATE
    assert second.document_id not in w.library.state.documents  # no second document
    assert len(w.library.state.contents) == 1 and w.library.state.chunks == chunks_before
    assert second.fields["key"] not in w.objects.objects
    upload = w.library.state.uploads[second.upload_id]
    assert (upload.outcome, upload.document_id) == (UploadOutcome.DUPLICATE, first.document_id)


def test_redelivery_after_a_duplicate_deletes_the_leftover_upload() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada")
    w.ingestion.ingest_upload(first.fields["key"])
    w.ingestion.ingest_upload(second.fields["key"])
    w.objects.objects[second.fields["key"]] = PDF  # say the delete hadn't happened
    assert w.ingestion.ingest_upload(second.fields["key"]) is None
    assert second.fields["key"] not in w.objects.objects
    assert len(w.library.state.contents) == 1


def test_upload_status_reports_the_outcome_only_to_its_learner() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada")
    pending = w.uploads.upload_status(UserId("ada"), second.upload_id)
    assert pending == UploadStatus(None, None, False)
    w.ingestion.ingest_upload(first.fields["key"])
    w.ingestion.ingest_upload(second.fields["key"])
    assert w.uploads.upload_status(UserId("ada"), second.upload_id) == UploadStatus(
        UploadOutcome.DUPLICATE, first.document_id, False
    )
    assert w.uploads.upload_status(UserId("bob"), second.upload_id) is None
    assert w.uploads.upload_status(UserId("ada"), UploadId("00000000-0000-4000-8000-000000000000")) is None
```

Keep `test_redelivery_after_success_changes_nothing` for one learner only (drop its `b`/duplicate part). Update `test_unknown_upload_and_non_upload_keys_are_skipped` to use `"contents/ada/c1.pdf"`. `test_processing.py`: replace `pages_key(content.sha256)` with `pages_key(content.owner_id, content.content_id)`. `test_retry_service.py` ~line 91: remove the assertion about the duplicate reason (and the duplicate setup if it only served that line). `fakes/ingest.py:32`: `Content.first_upload(ContentId(sha[:32]), sha, len(text), UserId(owner))` keeps working (argument order unchanged).

- [ ] **Step 3: Run** `cd backend && uv run pytest tests/unit/knowledge -q` — expect failures (missing names).

- [ ] **Step 4: Implement domain.** `content.py` module docstring: "A learner's file, keyed by `(owner_id, SHA-256)` the server computed from its bytes (PRD §9.4, §9.5; ADR 0011)." Replace key helpers and field as in Interfaces; `retry` docstring: "(Retry by the owner)". `document.py`: delete `DUPLICATE_UPLOAD`. `upload.py`: add `document_id: DocumentId | None = None` after `outcome`, import `DocumentId`.

- [ ] **Step 5: Implement ports** (signatures in Interfaces) and the fakes:

```python
# fakes/knowledge.py _Contents.insert_or_get
for existing in self._s.contents.values():
    if existing.owner_id == content.owner_id and existing.sha256 == content.sha256:
        return copy.deepcopy(existing), False

# _Documents
def get_by_content(self, content_id: ContentId) -> Document | None:
    found = [d for d in self._s.documents.values() if d.content_id == content_id]
    return copy.deepcopy(found[0]) if found else None

def remove(self, document_id: DocumentId) -> None:
    self._s.documents.pop(document_id, None)

# _Uploads
def get(self, upload_id: UploadId) -> Upload | None:
    found = self._s.uploads.get(upload_id)
    return copy.deepcopy(found) if found else None

def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome, document_id: DocumentId) -> None:
    upload = self._s.uploads[upload_id]
    upload.size, upload.outcome, upload.document_id = size, outcome, document_id
```

- [ ] **Step 6: Implement `IngestionService._store`:**

```python
        with self._uow() as tx:
            document = tx.documents.get_by_upload_for_update(upload_id)
            if document is None or not document.can_be_read_by(user_id):
                upload = tx.uploads.get(upload_id)
                if upload is not None and upload.user_id == user_id and upload.outcome is not None:
                    # A redelivered duplicate: its placeholder document is gone; only the copy may be left.
                    logger.info("upload %s was already handled", upload_id)
                    self._objects.delete(key)
                else:
                    logger.warning("no document for upload %s under this learner; ignoring", upload_id)
                return None, None
            ... (awaiting_upload / read unchanged)
            sha256 = hashlib.sha256(data).hexdigest()
            # Only this learner's contents are looked up (D18, D19): another learner's copy is never found.
            content, created = tx.contents.insert_or_get(
                Content.first_upload(ContentId(self._new_id()), sha256, len(data), user_id)
            )
            if created:
                self._objects.copy(key, content.s3_key)
                document.link_content(content.content_id)
                tx.documents.save(document)
                target, outcome = document.document_id, UploadOutcome.STORED
            else:
                existing = tx.documents.get_by_content(content.content_id)
                if existing is None:
                    raise LookupError(f"content {content.content_id} has no document")  # redelivered, then DLQ
                tx.documents.remove(document.document_id)  # no second document (US-11)
                target, outcome = existing.document_id, UploadOutcome.DUPLICATE
            tx.uploads.record_outcome(upload_id, len(data), outcome, target)
            tx.commit()
```

In `process_content`, `text_key = pages_key(content.owner_id, content.content_id)`. Remove the `DUPLICATE_UPLOAD` import. Update the module docstring "store its content once" → "store it as the learner's content".

- [ ] **Step 7: Implement `UploadService.upload_status`:**

```python
@dataclass(frozen=True)
class UploadStatus:
    """What became of an upload: `None` until the worker hashed it; the document it ended in (PRD US-11)."""

    outcome: UploadOutcome | None
    document_id: DocumentId | None
    archived: bool

    def upload_status(self, user_id: UserId, upload_id: UploadId) -> UploadStatus | None:
        """The caller's upload only; another learner's reads as unknown (None)."""
        with self._uow() as tx:
            upload = tx.uploads.get(upload_id)
            if upload is None or upload.user_id != user_id:
                return None
            document = tx.documents.get(upload.document_id) if upload.document_id else None
        if document is None or not document.can_be_read_by(user_id):
            return UploadStatus(upload.outcome, None, False)
        return UploadStatus(upload.outcome, document.document_id, document.archived)
```

Export `UploadStatus` from `knowledge/application/__init__.py`.

- [ ] **Step 8: Run** `uv run pytest tests/unit -q && uv run mypy` — the SQL adapter will fail mypy until Task 2; if so, fold Task 2's adapter changes in before committing.

- [ ] **Step 9: Commit** `Make contents per learner in the domain and the worker`.

### Task 2: Migration and the PostgreSQL adapter

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0008_per_learner_contents.py`
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_tables.py`, `adapters/sql_library.py`
- Test: `backend/tests/integration/knowledge/test_sql_library.py` (and a migration test if `tests/integration` has a pattern for one; otherwise test the data step through SQL in the same file)

**Interfaces:** Consumes Task 1 port signatures. Produces the schema: `contents.owner_id text not null`, unique `contents_owner_sha256 (owner_id, sha256)`, no `processed_by_user_id`; `uploads.document_id uuid null` (no FK: a later delete may remove the document).

- [ ] **Step 1: Write the migration:**

```python
"""Per-learner contents (PRD v2.23 D18, §9.4; ADR 0011): contents.owner_id, unique (owner_id, sha256); uploads.document_id.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09
"""

DUPLICATE_UPLOAD = "Duplicate uploads aren't supported yet"


def upgrade() -> None:
    op.add_column("contents", sa.Column("owner_id", sa.Text))
    # Duplicates failed until now, so each content has at most one owner's document.
    op.execute(
        "update contents c set owner_id = coalesce("
        "(select d.owner_id from documents d where d.content_id = c.content_id order by d.created_at limit 1),"
        " c.processed_by_user_id)"
    )
    op.alter_column("contents", "owner_id", nullable=False)
    op.drop_constraint("contents_sha256_key", "contents", type_="unique")
    op.create_unique_constraint("contents_owner_sha256", "contents", ["owner_id", "sha256"])
    op.drop_column("contents", "processed_by_user_id")
    # The document an upload ended in: its own, or the learner's existing one for a duplicate. No FK (delete).
    op.add_column("uploads", sa.Column("document_id", sa.Uuid(as_uuid=False)))
    op.execute(
        "update uploads u set document_id = d.document_id from documents d"
        " where d.upload_id = u.upload_id and d.content_id is not null"
    )
    # The interim duplicate failures have no file and can't be retried: remove them (the learner re-uploads).
    op.execute(
        sa.text(
            "delete from document_subjects where document_id in (select document_id from documents"
            " where content_id is null and failure_reason = :reason)"
        ).bindparams(reason=DUPLICATE_UPLOAD)
    )
    op.execute(
        sa.text("delete from documents where content_id is null and failure_reason = :reason").bindparams(
            reason=DUPLICATE_UPLOAD
        )
    )
    op.drop_constraint("documents_added_via", "documents", type_="check")
    op.create_check_constraint("documents_added_via", "documents", "added_via in ('upload', 'share', 'public', 'import')")


def downgrade() -> None:
    op.drop_constraint("documents_added_via", "documents", type_="check")
    op.create_check_constraint(
        "documents_added_via", "documents", "added_via in ('upload', 'dedupe', 'share', 'public', 'import')"
    )
    op.drop_column("uploads", "document_id")
    op.add_column("contents", sa.Column("processed_by_user_id", sa.Text))
    op.execute("update contents set processed_by_user_id = owner_id")
    op.drop_constraint("contents_owner_sha256", "contents", type_="unique")
    op.create_unique_constraint("contents_sha256_key", "contents", ["sha256"])  # fails if two learners share a file
    op.drop_column("contents", "owner_id")
```

Check the real constraint name first: `docker compose exec postgres psql ... -c "\d contents"` (or query `pg_constraint`); use the actual name.

- [ ] **Step 2: Adapter.** `sql_tables.py`: replace `processed_by_user_id` with `Column("owner_id", Text)`; add `Column("document_id", Uuid(as_uuid=False))` to `uploads`. `sql_library.py`: `_content` passes `UserId(row.owner_id)`; `insert_or_get` inserts `owner_id=content.owner_id`, `on_conflict_do_nothing(index_elements=["owner_id", "sha256"])`, and the fallback select filters `contents.c.owner_id == content.owner_id, contents.c.sha256 == content.sha256`. Add:

```python
    def get_by_content(self, content_id: ContentId) -> Document | None:
        row = self._conn.execute(select(documents).where(documents.c.content_id == content_id)).first()
        return self._load([row])[0] if row else None

    def remove(self, document_id: DocumentId) -> None:
        self._conn.execute(delete(document_subjects).where(document_subjects.c.document_id == document_id))
        self._conn.execute(delete(documents).where(documents.c.document_id == document_id))

    # _Uploads
    def get(self, upload_id: UploadId) -> Upload | None:
        row = self._conn.execute(select(uploads).where(uploads.c.upload_id == upload_id)).first()
        if row is None:
            return None
        return Upload(
            UploadId(str(row.upload_id)), UserId(row.user_id), row.created_at, row.bytes,
            UploadOutcome(row.outcome) if row.outcome else None,
            DocumentId(str(row.document_id)) if row.document_id else None,
        )

    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome, document_id: DocumentId) -> None:
        self._conn.execute(
            update(uploads).where(uploads.c.upload_id == upload_id)
            .values(bytes=size, outcome=outcome.value, document_id=document_id)
        )
```

- [ ] **Step 3: Integration tests** in `test_sql_library.py`: change the concurrent insert test (~line 67) so both callers are the same owner and still produce one row; add `test_two_owners_with_the_same_hash_get_two_contents` (insert as `ada` then `bob`: both `created is True`, two rows for the sha); replace the `DUPLICATE_UPLOAD` test (~92–118) with one that removes a document with `tx.documents.remove`, records `UploadOutcome.DUPLICATE` with the existing document id, and reads it back with `tx.uploads.get` (`outcome`, `document_id`); add a `get_by_content` assertion. Run: `docker compose up -d` then `cd backend && uv run --env-file ../.env alembic upgrade head` (or `make migrate`) and `uv run pytest -m integration tests/integration/knowledge -q`. Also verify downgrade/upgrade round-trip once: `uv run --env-file ../.env alembic downgrade 0007 && uv run --env-file ../.env alembic upgrade head`.

- [ ] **Step 4: Full backend checks** (Global Constraints), then commit `Key contents by owner and hash in PostgreSQL`.

### Task 3: `GET /uploads/{upload_id}` and the isolation test

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py`
- Test: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`
- Regenerate: `web/src/api/generated/`, `web/src/api/openapi.json` (`make api-client`; read the Makefile target and run it directly if `make` is missing)

**Interfaces:** Consumes `UploadService.upload_status`, `UploadStatus`. Produces operation `get_upload` → web `getUpload({ path: { upload_id } })` returning `UploadStatusResponse { upload_id: string; outcome: "stored" | "duplicate" | null; document_id: string | null; archived: boolean }`.

- [ ] **Step 1: Tests.** Route test: unknown id → 404; malformed id → 422; no token → 401; after a duplicate ingest → `{"upload_id": ..., "outcome": "duplicate", "document_id": <first document id>, "archived": false}`. Isolation test (`test_documents.py`):

```python
def test_two_learners_with_the_same_file_each_get_their_own_document_and_never_see_the_other() -> None:
    client, objects, ingestion = setup()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    a = client.post("/uploads", json={"file_name": "a.pdf"}, headers=A).json()
    b = client.post("/uploads", json={"file_name": "b.pdf"}, headers=B).json()
    for started in (a, b):
        objects.objects[started["fields"]["key"]] = pdf
        assert ingestion.ingest_upload(started["fields"]["key"]) is UploadOutcome.STORED

    [doc_a] = client.get("/documents", headers=A).json()
    [doc_b] = client.get("/documents", headers=B).json()
    assert (doc_a["document_id"], doc_b["document_id"]) == (a["document_id"], b["document_id"])
    assert doc_a["state"] == doc_b["state"] == "awaiting_subjects"
    assert client.get(f"/uploads/{a['upload_id']}", headers=A).json()["document_id"] == a["document_id"]
    assert client.get(f"/uploads/{a['upload_id']}", headers=B).status_code == 404
    assert client.get(f"/uploads/{b['upload_id']}", headers=A).status_code == 404


def test_a_learners_own_duplicate_points_to_their_document() -> None:
    client, objects, ingestion = setup()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    first = client.post("/uploads", json={"file_name": "a.pdf"}, headers=A).json()
    again = client.post("/uploads", json={"file_name": "copy.pdf"}, headers=A).json()
    for started in (first, again):
        objects.objects[started["fields"]["key"]] = pdf
        ingestion.ingest_upload(started["fields"]["key"])
    assert [d["document_id"] for d in client.get("/documents", headers=A).json()] == [first["document_id"]]
    assert client.get(f"/uploads/{again['upload_id']}", headers=A).json() == {
        "upload_id": again["upload_id"], "outcome": "duplicate", "document_id": first["document_id"], "archived": False,
    }
```

Also update the module docstring to mention US-11.

- [ ] **Step 2: Route** (place after `get_upload_limits` so `/uploads/limits` keeps matching first):

```python
class UploadStatusResponse(BaseModel):
    upload_id: str
    outcome: Literal["stored", "duplicate"] | None  # null until the worker has hashed the file
    document_id: str | None  # the upload's document, or the learner's existing one for a duplicate
    archived: bool


@router.get("/uploads/{upload_id}", operation_id="get_upload")
def get_upload(upload_id: UUID, principal: CurrentPrincipal, uploads: Uploads) -> UploadStatusResponse:
    """What became of the caller's upload; a duplicate points to the document they already have (PRD §8 US-11)."""
    found = uploads.upload_status(principal.user_id, UploadId(str(upload_id)))
    if found is None:
        raise HTTPException(404, "Upload not found")
    return UploadStatusResponse(
        upload_id=str(upload_id),
        outcome=found.outcome.value if found.outcome else None,
        document_id=found.document_id,
        archived=found.archived,
    )
```

Update the module docstring's route list.

- [ ] **Step 3:** Run backend checks; regenerate the API client; commit `Report what became of an upload`.

### Task 4: Web — the tray row says "Already in your library"

**Files:**
- Modify: `web/src/api/documents.ts`, `web/src/api/documents.test.ts`
- Modify: `web/src/components/UploadTray/UploadTray.tsx` (+ its CSS module and test if present)
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.test.tsx`
- Read first: `DESIGN.md`, `.design-shots/v0.10/library-already-in-library.*.png` (`make design-shots ROUND=v0.10 STATES="library-already-in-library" THEME=both`)

**Interfaces:** Consumes generated `getUpload`, `UploadStatusResponse`. Produces:
- `export type UploadStatus = UploadStatusResponse;`
- `loadUploadStatus(uploadId: string, apiClient?: Client): Promise<UploadStatus>` (throws `SessionExpiredError` on 401, `Error` otherwise)
- `UploadEvents.onStarted?: (documentId: string, uploadId: string) => void`
- `TrayItem = { id; name; size; status: "uploading" | "uploaded" | "failed" | "already"; progress; documentId?: string; archived?: boolean }`
- `LibraryPage` prop `loadUpload?: (uploadId: string) => Promise<UploadStatus>` (default `loadUploadStatus`).

- [ ] **Step 1: Tests.** `documents.test.ts`: `loadUploadStatus` GETs `/uploads/<id>` and returns the body; 401 → `SessionExpiredError`; `uploadPdf` calls `onStarted(document_id, upload_id)`. `UploadTray` test (create `UploadTray.test.tsx` if none): an `already` item shows "Already in your library" and an "Open document" link to `#document-<id>`; an archived one shows "Already in your library, archived" and no link. `LibraryPage.test.tsx`: an upload whose `loadUpload` first returns `{outcome: null}` then `{outcome: "duplicate", document_id: "d1", archived: false}` turns its tray row into "Already in your library" with the link and announces "<name>: Already in your library."; `outcome: "stored"` keeps "Uploaded · processing" and stops polling (assert `loadUpload` call count stays put after more time passes); replace the "Duplicate uploads aren't supported yet" fixture reason with "This file isn't a readable PDF" everywhere.

- [ ] **Step 2: API** in `documents.ts`:

```typescript
// What became of an upload (PRD US-11): null outcome until the worker has hashed it; a duplicate points to the learner's document.
export async function loadUploadStatus(uploadId: string, apiClient: Client = client): Promise<UploadStatus> {
  const { data, error, response } = await getUpload({ client: apiClient, path: { upload_id: uploadId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /uploads/${uploadId} failed (${response?.status ?? "no response"})`);
  return data;
}
```

and `events.onStarted?.(data.document_id, data.upload_id)`.

- [ ] **Step 3: Tray row:** status text for `already`: `item.archived ? "Already in your library, archived" : "Already in your library"`; icon `Info`; when not archived render `<a className={styles.link} href={`#document-${item.documentId}`}>Open document</a>` under the status (style with design tokens like the existing `.alreadyLink` in `LibraryPage.module.css`; never copy prototype CSS). Restore arrives with #108.

- [ ] **Step 4: LibraryPage.** In `send`, capture `started.uploadId` from `onStarted`. After a successful upload, `void watchUpload(id, started.uploadId, file.name, i, say)`:

```typescript
  const loadUploadRef = useRef(loadUpload);
  useEffect(() => {
    loadUploadRef.current = loadUpload;
  }, [loadUpload]);

  // The worker decides duplicates by the server hash (PRD D19); a duplicate's placeholder document disappears, so ask the upload.
  async function watchUpload(trayId: string, uploadId: string, name: string, i: number, say: () => void) {
    for (let tries = 0; tries < MAX_STATUS_POLLS && alive.current; tries++) {
      await new Promise((resolve) => setTimeout(resolve, pollMs));
      if (!alive.current) return;
      let found: UploadStatus;
      try {
        found = await loadUploadRef.current(uploadId);
      } catch (error) {
        if (error instanceof SessionExpiredError) return;
        continue; // try again on the next tick
      }
      if (found.outcome === null) continue;
      if (found.outcome === "duplicate" && found.document_id) {
        updateTray(trayId, { status: "already", documentId: found.document_id, archived: found.archived });
        parts.current[i] = `${name}: Already in your library.`;
        say();
        await refresh();
      }
      return;
    }
  }
```

with `const MAX_STATUS_POLLS = 150; // with the default 2 s poll, five minutes for the worker to hash the file`. Note `alive` is set false on unmount already.

- [ ] **Step 5:** `cd web && npx vitest run && npm run build`; commit `Show a server-detected duplicate on its upload row`.

### Task 5: Remove the Glacier tagger; update docs

**Files:**
- Delete: `backend/src/smart_tutor/apps/jobs/glacier_tagger.py`
- Modify: `backend/src/smart_tutor/apps/jobs/__init__.py` (docstring), `Makefile` (`.PHONY` and `glacier-tag` target), `deploy/helm/smart-tutor/charts/jobs/Chart.yaml`, `charts/jobs/values.yaml` (drop `glacierTagger` and its mention), `infra/smart_tutor_infra/stacks/storage.py` docstring (keys `contents/<owner_id>/<content_id>.pdf` and `.pages.json`; per-learner copies; drop "documents are archived, never deleted"), `infra/smart_tutor_infra/stacks/cluster.py` worker comment (`contents/<owner_id>/<content_id>.pdf`)
- Modify docs: `sdd/specs/2026-10-02-project-structure-design.md` (three Glacier mentions), `backend/src/smart_tutor/knowledge/README.md` (per-learner contents, keys, own-duplicate behavior, `upload_status`; drop "Until US-11…" and "deduplicated by SHA-256"), `sdd/prd.md` (§9.4 Upload row: add `document_id` — "the document the upload ended in: its own, or the learner's existing one for a duplicate (US-11)"; bump the status line to v2.24 and add a `Changes from v2.23` row naming #120 and `GET /uploads/{upload_id}`), `AGENTS.md` PRD version reference (v2.23 → v2.24)
- Grep afterwards: `grep -rni "glacier" --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=openwiki .` must only hit `sdd/` history (PRD decisions, reviews, ADRs, plans) and design files.

- [ ] **Step 1:** Make the edits. **Step 2:** `cd infra && uv run pytest`, `helm lint deploy/helm/smart-tutor`, backend checks. **Step 3:** Commit `Drop the Glacier tagger: PDFs stay in S3 Standard`.
