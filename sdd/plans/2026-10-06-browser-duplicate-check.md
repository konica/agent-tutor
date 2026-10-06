# Browser duplicate check ("Already in your library") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a learner picks a PDF, the browser hashes it (SHA-256) and asks the API whether that file is already in **their own** library; if so it skips the upload and shows "Already in your library" with a link to the document's row (issue #64).

**Architecture:** A new caller-scoped repository query `DocumentRepository.find_readable_by_sha256` (SQL: caller's non-archived documents joined to `contents` on `sha256`) behind `DocumentService.find_in_library`, exposed as `POST /documents/duplicate-check`. The web client hashes with `crypto.subtle.digest` (native, async, off the main thread) and calls the check before each upload; a failed check falls through to a normal upload.

**Tech Stack:** FastAPI + SQLAlchemy Core (backend), React + TypeScript + Vitest (web), generated `@hey-api` client in `web/src/api/generated`.

**Spec:** GitHub issue #64; PRD `sdd/prd.md` §8 US-2 (first criterion), §9.5, D19. Mockup: round v0.4 state `library-already-in-library` (info icon, file name, "Already in your library", an "Open document" link). Restore for archived documents is out of scope (US-10, #19).

## Global Constraints

- D19: the check answers **only** from the caller's documents (`readable_by(user_id)` in SQL, `Document.can_be_read_by` in the fake). It never links or reveals other learners' content; it creates nothing.
- The request body is `{"sha256": "<64 lowercase hex>"}`; anything else (uppercase, wrong length, unknown fields) is 422. No user id in the request; the user comes from the token.
- Response: `{"document_id": "<id>" | null}`, always 200 for a valid hash.
- A document matches only once its content is linked (`content_id` set by the worker). Duplicate-failed documents keep `content_id` null and never match. Archived documents don't match (archive restore is US-10).
- Copy is exactly `Already in your library` and the link text `Open document`.
- Hashing must not freeze the page: use `crypto.subtle.digest("SHA-256", …)` (async, runs off the main thread); never a JS-loop hash on the main thread.
- After changing the route run `make api-client` (or its two commands) so `web/src/api/openapi.json` and `web/src/api/generated/` are current; `test_openapi_snapshot.py` fails otherwise.
- Windows Git Bash: `PYTHONUTF8=1` for `lint-imports`.

## Review Focus

1. The same file in learner A's library and checked by learner B → `document_id: null` (isolation test, Task 1).
2. The check request fails (network/500) → the file still uploads normally; only a 401 ends the session (Task 2 test "uploads anyway when the check fails").
3. A pick of several files where one is already in the library → only the others upload; one combined live-region message (Task 2 test).
4. A document whose upload is still processing (no content yet) or that failed as a duplicate → no match; the server dedupe decides (Task 1 unit test).
5. Uppercase or malformed hash → 422, not a silent miss (Task 1 route test).

---

### Task 1: Backend duplicate-check endpoint

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (add abstract method to `DocumentRepository`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (`_Documents.find_readable_by_sha256`)
- Modify: `backend/tests/fakes/knowledge.py` (`_Documents.find_readable_by_sha256`)
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py` (`find_in_library`)
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py` (route + models)
- Modify: `backend/src/smart_tutor/knowledge/README.md` (mention the check under Rules)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`
- Test: `backend/tests/unit/knowledge/test_document_service.py`, `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Produces:
  - `DocumentRepository.find_readable_by_sha256(self, user_id: UserId, sha256: str) -> DocumentId | None` — the caller's oldest non-archived document whose linked content has this sha256.
  - `DocumentService.find_in_library(self, user_id: UserId, sha256: str) -> DocumentId | None`
  - HTTP `POST /documents/duplicate-check`, `operation_id="check_duplicate"`, body `DuplicateCheckRequest {sha256: str}` (pattern `^[0-9a-f]{64}$`, `extra="forbid"`), response `DuplicateCheckResponse {document_id: str | None}`.
  - Generated web SDK function `checkDuplicate` and types `DuplicateCheckRequest`, `DuplicateCheckResponse` (names as produced by `npm run api:generate`).

- [ ] **Step 1: Write failing unit tests for the service** (append to `backend/tests/unit/knowledge/test_document_service.py`)

```python
import hashlib

from fakes import fake_tools
from smart_tutor.knowledge.application import IngestionService

PDF = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
SHA = hashlib.sha256(PDF).hexdigest()


def _ingested(library: InMemoryLibrary, objects: FakeObjectStore, owner: str) -> str:
    uploads = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS)
    started = uploads.start_upload(UserId(owner), "paper.pdf")
    objects.objects[started.fields["key"]] = PDF
    IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS).ingest_upload(started.fields["key"])
    return started.document_id


def test_finds_the_callers_document_by_hash() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    document_id = _ingested(library, objects, "ada")
    service = DocumentService(library.unit_of_work)
    assert service.find_in_library(UserId("ada"), SHA) == document_id
    assert service.find_in_library(UserId("ada"), "0" * 64) is None


def test_another_learners_file_is_not_in_your_library() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    _ingested(library, objects, "ada")
    assert DocumentService(library.unit_of_work).find_in_library(UserId("bob"), SHA) is None


def test_an_unlinked_or_duplicate_failed_document_never_matches() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    first = _ingested(library, objects, "ada")
    _ingested(library, objects, "ada")  # fails as a duplicate; its content_id stays null
    uploads = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS)
    uploads.start_upload(UserId("carol"), "paper.pdf")  # still processing: no content yet
    service = DocumentService(library.unit_of_work)
    assert service.find_in_library(UserId("ada"), SHA) == first
    assert service.find_in_library(UserId("carol"), SHA) is None
```

Check `fakes/__init__.py` exports `fake_tools` and that `StartedUpload.fields["key"]` is how the key is reached (it is in `tests/isolation/test_documents.py`). Merge the new imports with the file's existing import block (ruff sorts them).

- [ ] **Step 2: Run them; expect FAIL** — `cd backend && uv run pytest tests/unit/knowledge/test_document_service.py -q` → `AttributeError: 'DocumentService' object has no attribute 'find_in_library'`.

- [ ] **Step 3: Implement port, fake, SQL adapter, service**

`ports/library.py`, in `DocumentRepository` after `list_readable_by`:

```python
    @abstractmethod
    def find_readable_by_sha256(self, user_id: UserId, sha256: str) -> DocumentId | None:
        """`can_read` in storage: the caller's oldest non-archived document whose content has this hash (PRD D19)."""
```

(add `DocumentId` to the `ids` import.)

`tests/fakes/knowledge.py`, in `_Documents`:

```python
    def find_readable_by_sha256(self, user_id: UserId, sha256: str) -> DocumentId | None:
        mine = sorted(
            (
                d
                for d in self._s.documents.values()
                if d.can_be_read_by(user_id)
                and d.content_id is not None
                and self._s.contents[d.content_id].sha256 == sha256
            ),
            key=lambda d: d.created_at,
        )
        return mine[0].document_id if mine else None
```

`adapters/sql_library.py`, in `_Documents` after `list_readable_by`:

```python
    def find_readable_by_sha256(self, user_id: UserId, sha256: str) -> DocumentId | None:
        found = self._conn.execute(
            select(documents.c.document_id)
            .select_from(documents.join(contents, documents.c.content_id == contents.c.content_id))
            .where(readable_by(user_id), documents.c.archived.is_(False), contents.c.sha256 == sha256)
            .order_by(documents.c.created_at, documents.c.document_id)
            .limit(1)
        ).scalar()
        return DocumentId(str(found)) if found else None
```

`application/document_service.py`, in `DocumentService`:

```python
    def find_in_library(self, user_id: UserId, sha256: str) -> DocumentId | None:
        """The caller's document holding this file, so the browser can skip uploading it (US-2, D19).

        Answers only from the caller's own documents; it never links content.
        """
        with self._uow() as tx:
            return tx.documents.find_readable_by_sha256(user_id, sha256)
```

- [ ] **Step 4: Run unit tests; expect PASS** — `uv run pytest tests/unit/knowledge -q`.

- [ ] **Step 5: Failing route + isolation tests**

Append to `backend/tests/unit/apps/api/test_knowledge_routes.py` (reuse its `client` fixture and `AUTH`; the fixture keeps `app.state.objects` and `app.state.ingestion`):

```python
def test_duplicate_check_finds_the_callers_document(client: TestClient) -> None:
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    started = client.post("/uploads", json={"file_name": "a.pdf"}, headers=AUTH).json()
    app = client.app
    app.state.objects.objects[started["fields"]["key"]] = pdf
    app.state.ingestion.ingest_upload(started["fields"]["key"])

    sha = hashlib.sha256(pdf).hexdigest()
    found = client.post("/documents/duplicate-check", json={"sha256": sha}, headers=AUTH)
    assert found.status_code == 200
    assert found.json() == {"document_id": started["document_id"]}
    missing = client.post("/documents/duplicate-check", json={"sha256": "0" * 64}, headers=AUTH)
    assert missing.json() == {"document_id": None}


@pytest.mark.parametrize("body", [{"sha256": "A" * 64}, {"sha256": "0" * 63}, {"sha256": "0" * 64, "user_id": "x"}, {}])
def test_duplicate_check_refuses_a_malformed_request(client: TestClient, body: dict[str, str]) -> None:
    assert client.post("/documents/duplicate-check", json=body, headers=AUTH).status_code == 422


def test_duplicate_check_needs_a_token(client: TestClient) -> None:
    assert client.post("/documents/duplicate-check", json={"sha256": "0" * 64}).status_code == 401
```

Look at how existing route tests reach `app.state` (e.g. `test_a_ready_document_lists_its_subject_with_the_resolved_name`) and copy that exactly. Also add `"check_duplicate"` to the set asserted in `test_openapi_names_the_operations`. Confirm what status the existing "needs a token" test expects and use the same.

Append to `backend/tests/isolation/test_documents.py`:

```python
def test_b_checking_as_file_hash_finds_nothing() -> None:
    client, objects, ingestion = setup()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = pdf
    ingestion.ingest_upload(stored["fields"]["key"])
    sha = hashlib.sha256(pdf).hexdigest()

    assert client.post("/documents/duplicate-check", json={"sha256": sha}, headers=A).json() == {
        "document_id": stored["document_id"]
    }
    assert client.post("/documents/duplicate-check", json={"sha256": sha}, headers=B).json() == {"document_id": None}
    assert client.get("/documents", headers=B).json() == []  # the check linked nothing
```

Update the module docstring to mention the browser hash check (D19).

- [ ] **Step 6: Run; expect FAIL (404/405)** — `uv run pytest tests/unit/apps/api tests/isolation -q`.

- [ ] **Step 7: Implement the route** in `apps/api/routes/knowledge.py` (update the module docstring: "…list the caller's documents, check whether a file is already in their library"):

```python
class DuplicateCheckRequest(BaseModel):
    # Only the hash: the library searched is the caller's, from the token (PRD D19).
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DuplicateCheckResponse(BaseModel):
    document_id: str | None


@router.post("/documents/duplicate-check", operation_id="check_duplicate")
def check_duplicate(
    body: DuplicateCheckRequest, principal: CurrentPrincipal, documents: Documents
) -> DuplicateCheckResponse:
    """Whether the caller's own library already holds this file, so the browser can skip the upload (PRD §8 US-2).

    Another learner's copy is never reported or linked; the server-side hash decides after upload (D19).
    """
    return DuplicateCheckResponse(document_id=documents.find_in_library(principal.user_id, body.sha256))
```

- [ ] **Step 8: Integration test for the SQL query** (append to `backend/tests/integration/knowledge/test_sql_library.py`; read `test_duplicate_document_keeps_content_id_null` first and build content + linked document the same way it does):

```python
def test_find_by_sha256_is_owner_only_and_skips_unlinked_and_archived(engine: Engine) -> None:
    # ada owns a document linked to content X; bob owns one too; ada also has an unlinked (processing) document.
    # Expect: ada → her linked document; bob's lookup → his own; carol → None; unknown hash → None.
    # Then: UPDATE documents SET archived = true for ada's document (via text()) → ada → None.
    ...
```

Write the body fully, reusing `start()`, `uid()`, and the content/link calls from `test_duplicate_document_keeps_content_id_null`. It runs only with `-m integration` against Compose; if Compose isn't running, report it as not run rather than skipping silently.

- [ ] **Step 9: Regenerate the web client** — from `backend/`: `uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json`, then `cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Confirm `checkDuplicate` appears in `web/src/api/generated/sdk.gen.ts`.

- [ ] **Step 10: README** — in `knowledge/README.md`, add `find_in_library` under services/Key classes and, in Rules, after the D19 sentence: "The browser duplicate check (`DocumentService.find_in_library`) looks only at the caller's linked, non-archived documents and links nothing."

- [ ] **Step 11: Full backend checks** — `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; plus `uv run pytest -m integration tests/integration/knowledge/test_sql_library.py` if Compose Postgres (port 10400) is up.

- [ ] **Step 12: Commit** — `git add -A backend web/src/api && git commit -m "Add a caller-scoped duplicate check by SHA-256"` (body: why — US-2 skip-upload, D19 owner-only).

---

### Task 2: Web — hash the picked file and skip uploads already in the library

**Files:**
- Modify: `web/src/api/documents.ts` (`sha256Hex`, `findInLibrary`)
- Modify: `web/src/api/documents.test.ts`
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.module.css`, `LibraryPage.test.tsx`
- Modify: `web/src/features/library/DocumentTable.tsx`, `DocumentTable.module.css` (row anchor + `:target` highlight)

**Interfaces:**
- Consumes: generated `checkDuplicate({ client, body: { sha256 }, throwOnError: false })` → `{ data?: { document_id: string | null }, error, response }`.
- Produces:
  - `export async function sha256Hex(file: Blob): Promise<string>` — lowercase hex.
  - `export async function findInLibrary(file: File, apiClient: Client = client): Promise<string | null>` — the caller's document id holding this file, or null; throws `SessionExpiredError` on 401 and `Error` on other failures.
  - `LibraryPage` prop `check?: (file: File) => Promise<string | null>` (default `findInLibrary`).
  - Table rows get `id={`document-${doc.document_id}`}`.

- [ ] **Step 1: Failing API tests** (append to `web/src/api/documents.test.ts`; copy the existing tests' fake-client pattern for `loadDocuments`/`uploadPdf`):

```ts
describe("sha256Hex", () => {
  it("hashes the file's bytes as lowercase hex", async () => {
    expect(await sha256Hex(new File(["abc"], "a.pdf"))).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("findInLibrary", () => {
  it("posts the hash and returns the caller's document id", async () => { /* fake client returning { document_id: "d1" }; assert body { sha256: <hex of file> } and result "d1" */ });
  it("returns null when the file isn't in the library", async () => { /* { document_id: null } → null */ });
  it("throws SessionExpiredError on 401", async () => { /* … */ });
  it("throws on other failures", async () => { /* 500 → rejects with Error */ });
});
```

Write the four bodies fully using the same fake `Client`/fetch technique as the file's existing `uploadPdf` tests.

- [ ] **Step 2: Run; expect FAIL** — `cd web && npx vitest run src/api/documents.test.ts`.

- [ ] **Step 3: Implement** in `web/src/api/documents.ts`:

```ts
// crypto.subtle hashes natively off the main thread, so a 50 MB file doesn't freeze the page.
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// Only the caller's own library is searched (PRD D19): another learner's copy reads as "not in your library".
export async function findInLibrary(file: File, apiClient: Client = client): Promise<string | null> {
  const sha256 = await sha256Hex(file);
  const { data, error, response } = await checkDuplicate({ client: apiClient, body: { sha256 }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`POST /documents/duplicate-check failed (${response?.status ?? "no response"})`);
  return data.document_id ?? null;
}
```

If jsdom's `File` lacks `arrayBuffer`, use `new Response(file).arrayBuffer()` instead — check by running the test.

- [ ] **Step 4: Run; expect PASS.**

- [ ] **Step 5: Failing page tests** (append to `LibraryPage.test.tsx` inside `describe("LibraryPage")`):

```tsx
  it("skips the upload of a file already in the library and links to its row", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async () => "d1");
    render(<LibraryPage loadLimits={limits} load={async () => [processing]} upload={upload} check={check} />);
    await screen.findByText("lewis-rag-2020.pdf");
    const file = new File(["%PDF"], "lewis-rag-2020.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    const list = await screen.findByRole("list", { name: "Already in your library" });
    expect(within(list).getByText("lewis-rag-2020.pdf")).toBeVisible();
    expect(within(list).getByText("Already in your library")).toBeVisible();
    expect(within(list).getByRole("link", { name: "Open document" })).toHaveAttribute("href", "#document-d1");
    expect(upload).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("lewis-rag-2020.pdf: Already in your library.");
    expect(document.getElementById("document-d1")).not.toBeNull();
  });

  it("uploads only the files not already in the library", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async (f: File) => (f.name === "have.pdf" ? "d1" : null));
    render(<LibraryPage loadLimits={limits} load={async () => [processing]} upload={upload} check={check} />);
    await screen.findByText("lewis-rag-2020.pdf");
    const have = new File(["%PDF a"], "have.pdf", { type: "application/pdf" });
    const fresh = new File(["%PDF b"], "fresh.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), [have, fresh]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledWith(fresh);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("have.pdf: Already in your library. Uploaded fresh.pdf. Processing."),
    );
  });

  it("uploads anyway when the check fails", async () => {
    const upload = vi.fn(async () => {});
    const check = vi.fn(async () => { throw new Error("500"); });
    render(<LibraryPage loadLimits={limits} load={async () => []} upload={upload} check={check} />);
    await screen.findByText("Upload your first document");
    const file = new File(["%PDF"], "x.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    await waitFor(() => expect(upload).toHaveBeenCalledWith(file));
  });

  it("does not check a rejected file", async () => {
    const check = vi.fn(async () => null);
    render(<LibraryPage loadLimits={limits} load={async () => []} upload={vi.fn()} check={check} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "notes.docx", { type: "application/msword" }), { applyAccept: false });
    expect(check).not.toHaveBeenCalled();
  });
```

Existing tests don't pass `check`; they would call the real `findInLibrary` (network) — so in those tests the default must not break them. Make the existing tests explicit: add a module-level `const notInLibrary = async () => null;` and pass `check={notInLibrary}` to every existing `render(<LibraryPage …>)` that uploads. Look at how the existing rejected-file test passes `applyAccept` and match it.

- [ ] **Step 6: Run; expect FAIL** — `npx vitest run src/features/library`.

- [ ] **Step 7: Implement LibraryPage**

- Import `Info` from `lucide-react` and `findInLibrary` from `../../api/documents`.
- Prop `check?: (file: File) => Promise<string | null>`; default `const defaultCheck = (file: File) => findInLibrary(file);` and destructure `check = defaultCheck`.
- State `const [alreadyIn, setAlreadyIn] = useState<{ name: string; documentId: string }[]>([]);`, cleared with `setRejected([])` at the start of `onPick`.
- In the loop, after the rejection `continue` and before `setStatus([... "Uploading …"])`:

```tsx
      let existing: string | null = null;
      try {
        existing = await check(file);
      } catch (error) {
        if (error instanceof SessionExpiredError) return; // the session screen replaces this page
        // Any other failure: upload anyway; the server-side hash decides (PRD D19).
      }
      if (existing) {
        setAlreadyIn((list) => [...list, { name: file.name, documentId: existing }]);
        parts.push(`${file.name}: Already in your library.`);
        setStatus(parts.join(" "));
        continue;
      }
```

  (Import `SessionExpiredError` from `../../auth/authClient` — confirm the path used in `api/documents.ts`.) Show `Checking ${file.name}…` in the status while hashing: `setStatus([...parts, \`Checking ${file.name}…\`].join(" "))` before the `check` call.
- Render, after the rejected list:

```tsx
      {alreadyIn.length > 0 && (
        <ul className={styles.already} aria-label="Already in your library">
          {alreadyIn.map((a, i) => (
            <li key={`${a.documentId}-${i}`}>
              <Info aria-hidden="true" strokeWidth={1.75} />
              <span>
                <span className={styles.rejectedName}>{a.name}</span>
                <span className={styles.alreadyNote}>Already in your library</span>
                <a className={styles.alreadyLink} href={`#document-${a.documentId}`}>Open document</a>
              </span>
            </li>
          ))}
        </ul>
      )}
```

- CSS (`LibraryPage.module.css`), neutral info style per the mockup, tokens only (check `DESIGN.md` for `--surface-2`/`--text-2`/`--accent-text` names; use what exists in `web/src/styles`):

```css
.already {
  margin: 0 0 var(--sp-4); padding: 0; list-style: none;
  border: 1px solid var(--border); border-radius: var(--r-md); background: var(--surface);
}
.already li { display: flex; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); }
.already li + li { border-top: 1px solid var(--border); }
.already svg { flex: none; width: 1.25rem; height: 1.25rem; color: var(--text-2); }
.alreadyNote { display: block; color: var(--text-2); }
.alreadyLink { display: inline-block; margin-top: var(--sp-1); color: var(--accent-text); font-weight: 600; }
```

- `DocumentTable.tsx`: `<tr key={doc.document_id} id={`document-${doc.document_id}`}>`; `DocumentTable.module.css`: `.table tbody tr:target { background: var(--accent-soft); }` and `scroll-margin-top: var(--sp-6)` on rows.

- [ ] **Step 8: Run web tests; expect PASS** — `npx vitest run`.

- [ ] **Step 9: Build** — `npm run build`.

- [ ] **Step 10: Visual check** — run the app or compare against `.design-shots/v0.4/library-already-in-library.{light,dark}.png`; at least confirm tokens resolve in both themes by reading `DESIGN.md`.

- [ ] **Step 11: Commit** — `git add web && git commit -m "Skip uploading a file already in the learner's library"` (body: why).
