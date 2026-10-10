# Document viewer beside the conversation (#123) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One click on a row in the chat's **Documents used** opens the PDF beside the conversation (split view), with an "Open in dialog" overlay, archived read-only mode with Restore, and a short-lived, renewed file link served only through `can_read`.

**Architecture:** The API gains `GET /documents/{id}/file`: a new `knowledge.application.ViewerService` reads the document through `can_read` (archived included), refuses processing/failed (409), and presigns a 5-minute S3 GET for `contents/<owner>/<content_id>.pdf`; the response carries the link and the document (title, authors, year, subjects, archived) so the viewer needs one call. The web app gains `src/features/viewer/`: a `useDocumentFile` hook (fetch + timed renewal), a `PdfLoader` seam over `pdfjs-dist` (fakeable in jsdom), a `DocumentViewer` body (toolbar, page canvas, skeleton, error/Retry, archived/Restore), a `DocumentPane` (labelled region for the chat split) and a `ViewerDialog` (modal overlay with details strip). `ChatPage` turns panel rows into buttons, lays out the split, collapses the panel, and forces the nav to its rail through a small `NavRail` context from `AppShell`.

**Tech Stack:** FastAPI, boto3 (S3 presign), AWS CDK (Python), React 19 + TypeScript + Vite, Vitest + Testing Library, `pdfjs-dist@6.3.289` (exact pin).

**Spec:** GitHub issue #123 (parent #118), PRD v2.26 §8 US-4b, §9.3 step 5, Q56/Q59/Q60; `DESIGN.md` → Chat ("Split view") and Accessibility; mockups `design-v0.10` states `viewer-document`, `viewer-dialog`, `viewer-archived`, `viewer-loading`, `viewer-error`.

## Global Constraints

- Link: presigned GET, valid **300 seconds**; only `ready`, `awaiting_subjects`, and archived documents in those states; `processing` or `failed` → **409**; missing or another learner's → **404**.
- Every read goes through `can_read` (`DocumentRepository.list_readable_by_ids`), never `get()` without the owner check.
- IAM: API role gets `s3:GetObject` on `<bucket>/contents/*` only (CDK). Bucket CORS allows `GET` as well as `POST` from the web origin (pdf.js fetches with XHR); LocalStack init too.
- Web: `pdfjs-dist` pinned exactly `6.3.289`; API calls only through `src/api/`; regenerate `src/api/generated` with the `api-client` Makefile command after the route lands.
- Tokens: add `--chat-min-w: 480px` to `web/src/styles/tokens.css` (DESIGN.md already lists it). Use existing tokens, `IconButton`, `Button`; never prototype CSS.
- Toolbar: one 40px row. Copy: "p. *n* / *N*", "Previous page", "Next page", "Zoom out", "Zoom in", "Open in dialog", "Close", "Back to side by side", "Archived · read-only", "Restore", "We couldn't open this document.", "Check your connection and try again.", "Retry". No download button.
- Accessibility: pane = `role="region"` labelled by its title; focus to the title (`tabIndex=-1` heading) on open and on swap; Esc/Close return focus to the opener. Dialog = `role="dialog" aria-modal`, focus to title, Tab trapped, Esc closes, focus returns to the "Open in dialog" button. PageUp/PageDown change page; a visually hidden `aria-live="polite"` line announces "Page n of N".
- Out of scope (later tickets): citation highlight and `GET /chunks/{id}`, Sources chips opening the viewer, "Ask about this", Library/details entry points (#109 not merged; the overlay component is built and used from the pane).
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npx vitest run && npm run build`. Infra: `cd infra && uv run pytest`.
- Commits: imperative subject, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A learner swaps documents (clicks another row) while the first is still loading: the late result of the first must never render in the pane (Task 5 test "a late load of a swapped-out document is ignored").
- The link expires while the pane is open and the learner presses Retry after a failure: Retry must fetch a fresh link, not reuse the stale URL (Task 4 test "retry asks for a new link").
- The document is deleted or archived between the panel load and the click: 404 → the error state, archived → read-only with Restore (Task 4 tests for 404 and archived).
- A deleted row in Documents used must not be clickable (Task 7 test "a deleted document's row is not a button").
- Keyboard: PageDown on the last page / PageUp on the first stays put and zoom is clamped (50–200%) (Task 5 tests).

---

### Task 1: API — `GET /documents/{id}/file`

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/ports/object_store.py` (add `presign_get`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/s3_object_store.py`
- Modify: `backend/tests/fakes/knowledge.py` (`FakeObjectStore.presign_get`)
- Create: `backend/src/smart_tutor/knowledge/application/viewer_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `ViewerService`, `DocumentFile`, `VIEWER_LINK_SECONDS`)
- Modify: `backend/src/smart_tutor/apps/api/services.py`, `deps.py` (`Viewer` dependency), `routes/knowledge.py`
- Modify: `backend/tests/fakes/api.py` (`viewer` field)
- Modify: `backend/src/smart_tutor/knowledge/README.md` (ViewerService rule)
- Test: `backend/tests/unit/knowledge/test_viewer_service.py`, `backend/tests/unit/knowledge/test_s3_object_store.py`, `backend/tests/isolation/test_documents.py`

**Interfaces:**
- Produces:
  - `ObjectStore.presign_get(self, key: str, *, expires_in: int) -> str` (abstract). S3: `generate_presigned_url("get_object", Params={"Bucket", "Key", "ResponseContentType": "application/pdf"}, ExpiresIn=expires_in)`. Fake: records `(key, expires_in)` in `self.presigned_gets` and returns `f"https://s3.test/{key}?expires={expires_in}"`.
  - `VIEWER_LINK_SECONDS = 300`
  - `@dataclass(frozen=True) class DocumentFile: view: DocumentView; url: str; expires_in: int`
  - `class ViewerService: __init__(self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore, max_attempts: int)`; `file(self, user_id: UserId, document_id: DocumentId) -> DocumentFile` raises `DocumentNotFoundError` (not readable/unknown) or `DocumentStateError("This document can't be opened until it has been processed")` (state `processing` or `failed`, or `content_id is None`).
  - Route `GET /documents/{document_id}/file`, `operation_id="get_document_file"`, response `DocumentFileResponse { url: str; expires_in: int; document: DocumentResponse }`; 404 `"Document not found"`, 409 with the state message. Declare `responses={404: ..., 409: ...}` like `threads.py` does.

- [ ] **Step 1: Failing unit tests** in `tests/unit/knowledge/test_viewer_service.py`, built like `test_archive_service.py` (use `InMemoryLibrary`, `FakeObjectStore`, and the same helpers it uses to create documents in each state). Cases:
  - ready document → `url` presigned for `contents/<owner>/<content_id>.pdf`, `expires_in == 300`, `view.title`, `view.authors`, `view.year` filled (from `list_readable_by_ids`).
  - `awaiting_subjects` → allowed; archived ready → allowed with `view.archived is True`.
  - `processing` and `failed` → `DocumentStateError`, and nothing presigned.
  - another learner's id and an unknown id → `DocumentNotFoundError`, nothing presigned.
  - `test_s3_object_store.py`: `presign_get` passes `Bucket`, `Key`, `ResponseContentType`, `ExpiresIn` (follow the existing presign_post test's stubbing style).
- [ ] **Step 2:** `cd backend && uv run pytest tests/unit/knowledge/test_viewer_service.py tests/unit/knowledge/test_s3_object_store.py -q` → FAIL (import error).
- [ ] **Step 3: Implement.**

```python
"""The document viewer's file link (PRD §8 US-4b, §9.3 step 5). Reads go through `can_read`, archived included."""

from collections.abc import Callable
from dataclasses import dataclass

from smart_tutor.knowledge.application.document_service import DocumentView, document_view
from smart_tutor.knowledge.domain.content import content_key
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError, DocumentStateError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectStore
from smart_tutor.shared.domain.ids import DocumentId, UserId

VIEWER_LINK_SECONDS = 300  # the viewer renews the link while it stays open
_OPENABLE = (DocumentState.READY, DocumentState.AWAITING_SUBJECTS)


@dataclass(frozen=True)
class DocumentFile:
    view: DocumentView
    url: str
    expires_in: int


class ViewerService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore, max_attempts: int) -> None:
        self._uow, self._objects, self._max_attempts = uow, objects, max_attempts

    def file(self, user_id: UserId, document_id: DocumentId) -> DocumentFile:
        """A short-lived link to the PDF of a processed document the caller can read."""
        with self._uow() as tx:
            found = tx.documents.list_readable_by_ids(user_id, [document_id])
        if not found:
            raise DocumentNotFoundError("This document isn't in your library")
        document = found[0]
        if document.state not in _OPENABLE or document.content_id is None:
            raise DocumentStateError("This document can't be opened until it has been processed")
        url = self._objects.presign_get(
            content_key(document.owner_id, document.content_id), expires_in=VIEWER_LINK_SECONDS
        )
        return DocumentFile(document_view(document, self._max_attempts), url, VIEWER_LINK_SECONDS)
```

  Route (in `routes/knowledge.py`, reusing `_document_response`):

```python
class DocumentFileResponse(BaseModel):
    url: str  # presigned GET for the PDF, valid `expires_in` seconds
    expires_in: int
    document: DocumentResponse


@router.get(
    "/documents/{document_id}/file",
    operation_id="get_document_file",
    responses={404: {"description": "Not the caller's document."}, 409: {"description": "Still processing or failed."}},
)
def get_document_file(
    document_id: UUID, principal: CurrentPrincipal, viewer: Viewer, subjects: Subjects
) -> DocumentFileResponse:
    """A 5-minute link to the PDF for the document viewer (PRD §8 US-4b, §9.3 step 5); archived documents open too."""
    try:
        found = viewer.file(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    except DocumentStateError as e:
        raise HTTPException(409, str(e)) from None
    names = subjects.names_for(principal.user_id, set(found.view.subject_ids))
    return DocumentFileResponse(url=found.url, expires_in=found.expires_in, document=_document_response(found.view, names))
```

  Wire `viewer=ViewerService(library, objects, max_attempts)` in `build_services`, add `viewer: ViewerService` to `ApiServices`, `_viewer` + `Viewer = Annotated[...]` in `deps.py` (and `__all__`), and `"viewer": ViewerService(library.unit_of_work, objects, max_attempts=3)` in `fakes/api.py`.
- [ ] **Step 4: Isolation + route tests.** Append to `tests/isolation/test_documents.py` (same `setup()`; make a ready document by ingesting and choosing the "General" subject id as `test_b_never_sees_the_subjects_of_a_document` does):

```python
def test_b_cannot_get_a_documents_file_link() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    doc = stored["document_id"]

    assert client.get(f"/documents/{doc}/file", headers=B).status_code == 404
    assert all(not key.startswith("contents/learner-a/") for key, _ in objects.presigned_gets)
    mine = client.get(f"/documents/{doc}/file", headers=A)
    assert mine.status_code == 200 and mine.json()["expires_in"] == 300
    assert mine.json()["document"]["document_id"] == doc
```

  Plus, in a route test file next to the other API knowledge route tests (find with `grep -rln "subject-suggestions" backend/tests/unit/apps/api`), a processing document → 409 and an archived one → 200 with `document.archived` true.
- [ ] **Step 5:** Run the full backend checks (Global Constraints). Fix `mypy`/`ruff`/`lint-imports`.
- [ ] **Step 6:** README: add `ViewerService` (`file`) to Key classes and a rule sentence: "`ViewerService.file` reads through `can_read` (archived included), serves only `ready` and `awaiting_subjects` documents (409 otherwise), and presigns a 300-second GET for `contents/<owner_id>/<content_id>.pdf`; the viewer renews it." Add `presign_get` to the `ObjectStore` mention.
- [ ] **Step 7: Commit** `Serve a short-lived file link for the document viewer (#123)`.

### Task 2: Infra and local storage — API reads `contents/*`, CORS allows GET

**Files:**
- Modify: `infra/smart_tutor_infra/stacks/cluster.py` (API policy + comment)
- Modify: `infra/smart_tutor_infra/stacks/storage.py` (CORS rule methods `[POST, GET]`; module docstring)
- Modify: `local/localstack/init/ready.d/10-smart-tutor.sh` (`"AllowedMethods": ["POST", "GET"]`)
- Modify: `infra/tests/test_synth.py`, `infra/tests/test_storage.py`
- Modify: `sdd/prd.md` (line with "CORS for presigned POST from the web origin" → "CORS for presigned POST and the viewer's presigned GET from the web origin"; bump status-line version to v2.27 with a one-line change note), `AGENTS.md` PRD version reference `(v2.26)` → `(v2.27)`.

- [ ] **Step 1: Failing tests.** In `test_synth.py::test_each_service_gets_only_its_own_s3_sqs_and_bedrock_access`, replace the API comment/asserts:

```python
    # The API signs uploads into uploads/, presigns the viewer's GET on contents/, and sends Retry messages.
    assert "contents/*" in api["s3:GetObject"] and "uploads/" not in api["s3:GetObject"]
    assert "s3:DeleteObject" not in api
```

  In `test_storage.py::test_documents_bucket_cors_allows_only_the_cloudfront_address`, expect `"AllowedMethods": ["POST", "GET"]`.
- [ ] **Step 2:** `cd infra && uv run pytest -q` → those two FAIL.
- [ ] **Step 3:** Add `iam.PolicyStatement(actions=["s3:GetObject"], resources=[f"{bucket_arn}/contents/*"])` to the Api policy (update its comment: "...presigns the document viewer's GET on contents/ (US-4b)..."); CORS `allowed_methods=[s3.HttpMethods.POST, s3.HttpMethods.GET]`; LocalStack script; PRD + AGENTS.md version.
- [ ] **Step 4:** `cd infra && uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** `Let the API presign viewer GETs on contents (#123)`.

### Task 3: Web API — regenerate client, `loadDocumentFile`, pin pdfjs, token

**Files:**
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*` (run from repo root: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`)
- Modify: `web/src/api/documents.ts`, `web/src/api/documents.test.ts`
- Modify: `web/package.json`, `web/package-lock.json` (`npm install --save-exact pdfjs-dist@6.3.289`)
- Modify: `web/src/styles/tokens.css` (`--chat-min-w: 480px;` after `--chat-panel-w`)

**Interfaces:**
- Produces in `web/src/api/documents.ts`:

```ts
export type DocumentFile = { url: string; expiresAt: number; document: DocumentResponse }; // expiresAt: Date.now() ms
export class DocumentNotOpenableError extends Error {} // 409: processing or failed
export class DocumentNotFoundError extends Error {}    // 404: gone or not the learner's
export async function loadDocumentFile(documentId: string, apiClient: Client = client, now: () => number = Date.now): Promise<DocumentFile>
```

- [ ] **Step 1: Failing tests** in `documents.test.ts`, mocking fetch on a test client the way the existing `restoreDocument`/`retryProcessing` tests do: 200 → `{url, expiresAt: now()+300_000, document}`; 404 → `DocumentNotFoundError`; 409 → `DocumentNotOpenableError`; 401 → `SessionExpiredError`; 500 → plain `Error`.
- [ ] **Step 2:** `cd web && npx vitest run src/api/documents.test.ts` → FAIL.
- [ ] **Step 3: Implement** with the generated `getDocumentFile`:

```ts
export async function loadDocumentFile(documentId: string, apiClient: Client = client, now: () => number = Date.now): Promise<DocumentFile> {
  const { data, error, response } = await getDocumentFile({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (response?.status === 404) throw new DocumentNotFoundError("Document not found");
  if (response?.status === 409) throw new DocumentNotOpenableError(failure(error).message);
  if (!data) throw new Error(`GET /documents/${documentId}/file failed (${response?.status ?? "no response"})`);
  return { url: data.url, expiresAt: now() + data.expires_in * 1000, document: data.document };
}
```

- [ ] **Step 4:** Install pdfjs exact; add the token. `npx vitest run src/api && npm run build` → PASS.
- [ ] **Step 5: Commit** `Add the document file link to the web API client (#123)`.

### Task 4: `useDocumentFile` and the `PdfLoader` seam

**Files:**
- Create: `web/src/features/viewer/useDocumentFile.ts`, `useDocumentFile.test.tsx`
- Create: `web/src/features/viewer/pdf.ts` (types + real pdf.js loader)

**Interfaces:**
- Produces:

```ts
// pdf.ts
export type PdfPage = { width: number; height: number; render(canvas: HTMLCanvasElement, scale: number): Promise<void> }; // width/height at scale 1, CSS px
export type PdfDoc = { numPages: number; page(n: number): Promise<PdfPage>; destroy(): void };
export type PdfLoader = (url: string) => Promise<PdfDoc>;
export const loadPdf: PdfLoader; // pdfjs-dist; worker from "pdfjs-dist/build/pdf.worker.min.mjs?url"

// useDocumentFile.ts
export type FileState =
  | { status: "loading" }
  | { status: "ready"; file: DocumentFile }
  | { status: "failed"; reason: "not-found" | "not-openable" | "error" };
export function useDocumentFile(documentId: string, load?: (id: string) => Promise<DocumentFile>):
  { state: FileState; retry: () => void; setDocument: (d: DocumentResponse) => void };
```

  Real loader (unit tests never import pdfjs; keep it a thin file):

```ts
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;
const CSS_PER_PT = 96 / 72;

export const loadPdf: PdfLoader = async (url) => {
  const pdf = await getDocument({ url, isEvalSupported: false }).promise;
  return {
    numPages: pdf.numPages,
    destroy: () => void pdf.destroy(),
    page: async (n) => {
      const p = await pdf.getPage(n);
      const base = p.getViewport({ scale: CSS_PER_PT });
      return {
        width: base.width,
        height: base.height,
        render: async (canvas, scale) => {
          const ratio = window.devicePixelRatio || 1;
          const viewport = p.getViewport({ scale: CSS_PER_PT * scale * ratio });
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = `${viewport.width / ratio}px`;
          canvas.style.height = `${viewport.height / ratio}px`;
          await p.render({ canvas, viewport }).promise;
        },
      };
    },
  };
};
```

  (Check the pdfjs 6.3 `render` parameter shape in `node_modules/pdfjs-dist/types/src/display/api.d.ts`; if it needs `canvasContext`, pass `canvas.getContext("2d")!` instead.)

- Behavior of `useDocumentFile`: loads on mount and when `documentId` changes (ignores replies for a previous id or after unmount); 404 → `not-found`, 409 → `not-openable`, else `error`; `SessionExpiredError` → stays `loading` (the session screen takes over). **Renewal:** while ready, a timer fires at `expiresAt - 30_000` (min 0) and fetches a fresh link, replacing `file` (keep the old one if renewal fails; the next Retry fetches again). `retry()` always fetches a new link. `setDocument` replaces `file.document` (used after Restore).

- [ ] **Step 1: Failing tests** (`vi.useFakeTimers()`; `renderHook`): loads then ready; renews ~270s later (load called twice, url updated); 404/409/other map to reasons; **retry asks for a new link** (load called again, even right after a failure); a late reply for an old `documentId` is ignored after rerender with a new id; unmount clears the timer (no call after unmount).
- [ ] **Step 2:** `npx vitest run src/features/viewer` → FAIL. **Step 3:** implement. **Step 4:** PASS + `npm run build`.
- [ ] **Step 5: Commit** `Fetch and renew the viewer's file link (#123)`.

### Task 5: `DocumentViewer` — toolbar, page, states

**Files:**
- Create: `web/src/features/viewer/DocumentViewer.tsx`, `DocumentViewer.module.css`, `DocumentViewer.test.tsx`

**Interfaces:**
- Consumes: `useDocumentFile`, `PdfLoader`/`loadPdf`, `restoreDocument` (`src/api/documents.ts`).
- Produces:

```ts
type Props = {
  documentId: string;
  /** "pane": toolbar ends with Open in dialog + Close (X). "dialog": toolbar starts with a back/close text button. */
  mode: "pane" | "dialog";
  initialPage?: number;                 // default 1
  titleRef?: Ref<HTMLHeadingElement>;   // the parent focuses it on open
  titleId?: string;                     // for aria-labelledby on the region/dialog
  onClose: () => void;
  closeLabel?: string;                  // dialog: "Back to side by side" (from the pane) or "Close"
  onOpenInDialog?: (page: number) => void; // pane only; shows the Open in dialog button when set
  openInDialogRef?: Ref<HTMLButtonElement>;
  onPageChange?: (page: number) => void;
  showDetails?: boolean;                // dialog: the details strip
  loadFile?: (id: string) => Promise<DocumentFile>;  // tests
  loadPdfDoc?: PdfLoader;                            // tests
  restore?: (id: string) => Promise<DocumentResponse>; // tests
};
export function DocumentViewer(props: Props): JSX.Element;
```

- Layout (DESIGN.md compact, mockups): `.viewer` is a column flex filling its parent; `.toolbar` 40px, `border-bottom: 1px solid var(--border)`, `background: var(--surface)`, `gap: var(--sp-2)`, `padding: 0 var(--sp-2)`. Order: [dialog: close text `Button variant="quiet" size="sm"` with `ArrowLeft` (from pane) or `X` icon] · `<h2 tabIndex={-1}>` title (ellipsis, `font-size: var(--fs-14)`, weight 600) · [archived: badge "Archived · read-only" using `--attn`/`--attn-soft` with `Archive` icon, then `Button size="sm" icon={RotateCcw}` "Restore"] · prev `IconButton ChevronLeft "Previous page"` · `<span>` "p. {page} / {N}" (`font-family: var(--font-mono)`, `font-size: var(--fs-12)`) · next `ChevronRight "Next page"` · separator · `Minus "Zoom out"` · "{zoom}%" · `Plus "Zoom in"` · [pane: separator, `Maximize2 "Open in dialog"` (tooltip on), `X "Close"`]. Below in the dialog: `.details` strip (32px, `--fs-12`, `--text-2`): authors joined ", " (or nothing), year, "{N} pages", subject chips via `SubjectChip`, "Archived" when archived. `.canvasArea`: `flex:1; overflow:auto; background: var(--surface-3)`; the page is a white card (`background:#fff; box-shadow: var(--shadow-sm); margin: var(--sp-4) auto`) holding the `<canvas>`.
- States: file `loading` or PDF loading → skeleton (a page-shaped card with `--surface-2` bars, `aria-busy="true"`, visually hidden "Loading document"); failure (file failed with `error`/`not-found`, PDF load or page render rejected) → centered card with `CircleAlert`, "We couldn't open this document.", "Check your connection and try again." and `Button icon={RefreshCw}` "Retry" (calls `retry()` — new link — then reloads the PDF at the current page); `not-openable` → same card with "This document can't be opened until it has been processed." and no Retry. Toolbar title shows `file.document.title` once known (else "Document").
- Page/zoom: page clamps 1..N; zoom steps `[50, 75, 100, 125, 150, 200]`, default 100; buttons disabled at the ends. Keyboard on the viewer root (`onKeyDown`): PageDown → next, PageUp → previous (preventDefault). A visually hidden `<p aria-live="polite">` holds "Page {page} of {N}" after the first render. `onPageChange(page)` fires on change.
- Loading race: each PDF load captures its URL; when `documentId` changes or the component unmounts, the previous `PdfDoc` is destroyed and its late result ignored. Loading the PDF depends on the first ready URL for a document and on Retry — **not** on each renewal (renewing the link must not reload the PDF).
- Restore: calls `restore(id)`; on success `setDocument(updated)` (badge goes, viewer stays open); on failure shows inline `--danger` text "Couldn't restore. Try again." beside the button.

- [ ] **Step 1: Failing tests** with fake `loadFile` (resolves `{url:"u1", expiresAt: Date.now()+300_000, document: {…title:"ReAct", archived:false, authors:["Yao"], year:2022, subjects:[]…}}`) and fake `loadPdfDoc` (numPages 3; `render` resolves). Cases: skeleton then title + "p. 1 / 3"; next/prev buttons and PageDown/PageUp change page and the live line reads "Page 2 of 3"; **PageDown on the last page stays**; zoom in/out labels change "100%"→"125%", **clamped at 50% and 200%** (buttons disabled); load failure → error card → Retry calls `loadFile` again and shows the page; 409 → not-openable copy, no Retry; archived → "Archived · read-only" + Restore → `restore` called, badge gone, still open; `initialPage=3` opens at "p. 3 / 3"; **a late load of a swapped-out document is ignored** (rerender with a new `documentId` while the first `loadPdfDoc` is pending; resolve the first late; title/page count stay from the second); Close button calls `onClose`; Open in dialog passes the current page; no element with name /download/i.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `npx vitest run src/features/viewer && npm run build` PASS.
- [ ] **Step 5: Commit** `Render a document in the viewer with paging, zoom, and states (#123)`.

### Task 6: `DocumentPane`, `ViewerDialog`, and the shared focus trap

**Files:**
- Create: `web/src/components/Dialog/useFocusTrap.ts` (extracted from `Dialog.tsx`); Modify: `Dialog.tsx` to use it (its tests must still pass unchanged)
- Create: `web/src/features/viewer/DocumentPane.tsx`, `DocumentPane.module.css`, `ViewerDialog.tsx`, `ViewerDialog.module.css`, `ViewerDialog.test.tsx`, `DocumentPane.test.tsx`

**Interfaces:**
- Produces:

```ts
// useFocusTrap.ts — moves focus in on mount (to [data-autofocus] or the first focusable), traps Tab, Escape calls onClose,
// and on unmount returns focus to `returnTo` when given, else to the element focused before mount.
export function useFocusTrap(onClose: () => void, returnTo?: RefObject<HTMLElement | null>): {
  ref: RefObject<HTMLDivElement | null>; onKeyDown: (e: KeyboardEvent) => void };

// DocumentPane.tsx — the chat's split pane: <section role="region" aria-labelledby={titleId}>, focuses the title on mount
// and whenever documentId changes; Escape (not swallowed by a child) calls onClose; holds the dialog state and renders
// ViewerDialog (from the pane) when "Open in dialog" is pressed; when the dialog closes, focus goes to the Open in dialog
// button and the pane jumps to the dialog's last page.
export function DocumentPane(props: { documentId: string; onClose: () => void; viewerDeps?: ViewerDeps }): JSX.Element;

// ViewerDialog.tsx — the overlay: scrim + `role="dialog" aria-modal="true" aria-labelledby={titleId}`, width var(--viewer-w),
// height calc(100dvh - 32px), DocumentViewer mode="dialog" showDetails, title focused on open (data-autofocus on the h2
// via titleRef), Tab trapped, Escape closes.
export function ViewerDialog(props: { documentId: string; initialPage?: number; closeLabel: string;
  onClose: (page: number) => void; returnFocusTo?: RefObject<HTMLElement | null>; viewerDeps?: ViewerDeps }): JSX.Element;

export type ViewerDeps = Pick<DocumentViewerProps, "loadFile" | "loadPdfDoc" | "restore">; // export DocumentViewerProps from DocumentViewer.tsx
```

  In `useFocusTrap`, the h2 has `tabIndex={-1}`, so add `[data-autofocus]` focus before the FOCUSABLE fallback (already how `Dialog` works). Escape inside the dialog must `stopPropagation()` so the pane underneath doesn't also close.

- [ ] **Step 1: Failing tests.**
  - `ViewerDialog.test.tsx`: on open the dialog's title has focus; Tab from the last control wraps to the first and Shift+Tab from the first wraps to the last; Escape calls `onClose` with the current page; the details strip shows "Yao", "2022", "3 pages"; after unmount focus returns to the `returnFocusTo` element.
  - `DocumentPane.test.tsx`: region named by the document title; title focused on mount and again after rerender with another `documentId`; Escape calls `onClose`; "Open in dialog" at page 2 opens the dialog at "p. 2 / 3"; Escape in the dialog closes only the dialog (pane `onClose` not called), focus lands on the "Open in dialog" button, the dialog's Close label is "Back to side by side".
  - Existing `Dialog.test.tsx` passes unchanged.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `npx vitest run src/components src/features/viewer && npm run build` PASS.
- [ ] **Step 5: Commit** `Open a document in a side pane or a dialog (#123)`.

### Task 7: Chat split view, panel rows, nav rail

**Files:**
- Create: `web/src/components/AppShell/NavRail.tsx` (context)
- Modify: `web/src/components/AppShell/AppShell.tsx` (provider; `collapsed || forced`)
- Modify: `web/src/features/chat/ConversationPanel.tsx`, `.module.css`, `.test.tsx`
- Modify: `web/src/features/chat/ChatPage.tsx`, `ChatPage.module.css`, `ChatPage.test.tsx`
- Modify: `web/src/components/AppShell` test file if one exists (`ls web/src/components/AppShell`), else add `NavRail.test.tsx`

**Interfaces:**
- Produces:

```ts
// NavRail.tsx
export const NavRailContext = createContext<(on: boolean) => void>(() => {});
/** While `on`, the app nav shows its rail; the learner's own choice comes back when it turns off or the caller unmounts. */
export function useForceNavRail(on: boolean): void; // useEffect: set(on); cleanup set(false)
```

  `AppShell`: `const [forced, setForced] = useState(false)`; wrap `<SideNav … collapsed={collapsed || forced} />` and the `<Outlet/>` in `<NavRailContext.Provider value={setForced}>`. The SideNav's own toggle still works (re-openable): when forced and the learner toggles, call `setForced(false)` instead of `toggle()` so the nav opens without changing the saved choice.

- `ConversationPanel`: new prop `onOpen?: (documentId: string, opener: HTMLElement) => void` and `openId?: string | null`. A non-deleted row renders a full-width `<button type="button" className={styles.rowButton} aria-current={openId === d.document_id ? "true" : undefined} onClick={(e) => onOpen?.(d.document_id, e.currentTarget)}>` holding the icon, title, badge (row styles move onto the button: hover `--surface-2`, open row `--accent-soft` background, focus ring per DESIGN.md). Deleted rows stay plain `<li>` content. Update the doc comment ("Rows open nothing yet (#123)" → "A row opens the document beside the conversation (US-4b)").
- `ChatPage`: state `viewer: { documentId: string } | null`, `opener = useRef<HTMLElement | null>(null)`, `panelBeforeViewer` handling: while a viewer is open the panel is hidden (`showPanel = panelOpen && !viewer || panelDuringViewer`), where the header toggle during the split flips a local `panelDuringViewer` instead of the saved choice; closing the viewer resets `panelDuringViewer=false` (saved choice comes back). `useForceNavRail(viewer !== null)`. Open: `opener.current = el; setViewer({documentId})` (swap in place when already open). Close: `setViewer(null)` then focus `opener.current` (in an effect after the pane unmounts; if the opener left the DOM because the panel is hidden, focus the panel toggle button). A new question closes the viewer (`submit` → `setViewer(null)`).
- Layout CSS: `.withViewer { grid-template-columns: minmax(var(--chat-min-w), 2fr) minmax(0, 3fr); }` and with the panel too `.withPanel.withViewer { grid-template-columns: var(--chat-panel-w) minmax(var(--chat-min-w), 2fr) minmax(0, 3fr); }`; the pane gets `border-left: 1px solid var(--border); min-width: 0; min-height: 0`.

- [ ] **Step 1: Failing tests.**
  - `ConversationPanel.test.tsx`: a ready row is a button named by its title; clicking calls `onOpen(id, button)`; **a deleted document's row is not a button**; `openId` row has `aria-current="true"`.
  - `ChatPage.test.tsx` (reuse its existing helpers for asking a question and stubbing `loadUsed`; pass viewer fakes through a new optional prop `viewerDeps?: ViewerDeps` forwarded to `DocumentPane`): after an answer, clicking the "ReAct" row shows a region named "ReAct" at "p. 1 / 3" with its title focused, and the conversation panel (`aside` "Conversation") is gone; clicking another row swaps the region's name; Close removes the region, the panel returns, and focus is on the "ReAct" row button; Escape in the pane does the same; header "Show panel" during the split shows the panel without writing `smart-tutor.chat-panel-open` to localStorage.
  - Nav rail: render `AppShell` routes with a child calling `useForceNavRail(true)` and assert the nav has its collapsed class/`aria-expanded` state the SideNav tests already check; unmounting the child restores it.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `npx vitest run && npm run build` PASS (all web tests).
- [ ] **Step 5: Commit** `Open a used document beside the conversation in one click (#123)`.

### Task 8: Visual check against the mockups, docs, and full checks

**Files:**
- Modify (only if mismatched): viewer CSS modules
- Modify: `web/src/features/chat/ChatPage.module.css` comment "Not buttons until the viewer exists (#124)" stays (Sources chips are #124).

- [ ] **Step 1:** Run all checks from Global Constraints (backend, web, infra). All PASS.
- [ ] **Step 2:** Compare against `.design-shots/v0.10/viewer-*.light.png` (render with `make design-shots ROUND=v0.10 STATES="viewer-document,viewer-dialog,viewer-archived,viewer-loading,viewer-error" THEME=both`, or the `npm run design:shots` command in `web/`). If the Compose stack is available, start the app (`docker compose up -d`, `make api`, `make web`), sign in as `learner@example.com`, ask a question, and click a Documents used row at 1280 and 1440 widths: the conversation stays ≥ 480px. Record any mockup/PRD conflict for the PR description.
- [ ] **Step 3: Commit** any fixes: `Match the viewer to design round v0.10 (#123)`.
