# Drop Zone and Upload Tray Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ticket #65 (US-2, brief §6.3): files dragged anywhere over the Library highlight the page and upload on drop; several PDFs upload in parallel, each with its own progress bar in a fixed upload tray; rows show "Uploading" until the bytes reach storage.

**Architecture:** `uploadPdf` sends the file to S3 with `XMLHttpRequest` (fetch can't report upload progress) and reports `onStarted(documentId)` and `onProgress(fraction)`. A presentational `UploadTray` component renders tray items. A `usePageDrop` hook listens on `document` for file drags while the Library is mounted. `LibraryPage` runs one pipeline per file (reject → check → upload) concurrently and keeps the tray items and the set of document ids still uploading.

**Tech Stack:** React 19 + TypeScript, CSS Modules with tokens from `web/src/styles/tokens.css`, `lucide-react` icons, Vitest + Testing Library (jsdom).

**Spec:** GitHub issue #65 (acceptance criteria below), `sdd/design/brief.md` §6.3, `DESIGN.md`, mockup round v0.4 states `library-drop-active`, `library-uploading`, `library-first-processing` (prototype `v03.css` `.tray`, `.drop-overlay`, `.bar`; `js/core.js` `renderTray`; `js/documents.js` drop handlers at tag `design-v0.4`).

Acceptance criteria (#65):
- Dropping three PDFs onto the page uploads all three, each with its own progress bar in the tray.
- The drop highlight appears on drag-over and clears on drag-leave or drop; dropping non-PDF files goes through the same rejection as picking them.
- Upload works by keyboard; progress is announced to screen readers.
- Matches `library-drop-active` and `library-uploading` at 1440px and 1280px in light and dark.
- `npm run build` and web tests pass.

## Global Constraints

- Every color, font size, space, radius, shadow and duration is a `var(--…)` from `tokens.css`; control sizes, 1–3px borders and z-index may be literal.
- Icons: `lucide-react`, `strokeWidth={1.5}`, `aria-hidden="true"` unless the icon is the only label; icon-only buttons have `aria-label`.
- One polite live region (the page's `role="status"` paragraph) carries upload results; the tray is not a live region.
- Required wording, verbatim: overlay "Drop PDFs to upload"; tray header "Uploading N files…" while any file uploads, else "Uploads · N files" (singular "file" for 1); item statuses "Uploading · X MB", "Uploaded · processing", "Upload failed"; badge label "Uploading"; progress bar label "Upload progress for {file name}"; tray buttons "Collapse uploads" / "Expand uploads" / "Close uploads"; first-run card note "Or drop files anywhere on this page. You can add several at once."
- The tray's Close button is shown only when no file is uploading.
- Prototype HTML/CSS is a spec, never pasted: rebuild with components and tokens.
- Run web commands from `web/`: `npx vitest run <path>`; full check `npm run build && npm test`.
- Commit subjects in the imperative mood; body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Dragging non-file content (selected text, a link) over the page must not show the overlay or swallow the drop — test in Task 3.
2. Dragging across child elements fires nested dragenter/dragleave; the overlay must stay until the drag really leaves the page — test in Task 3.
3. One file of a batch failing (storage error) must not stop or mark the other files — test in Task 4.
4. A second drop while the first batch is still uploading adds to the same tray, newest first, and Close stays hidden until all finish — tests in Tasks 2 and 4.
5. Storage answering non-2xx, or the network failing, must reject the upload (not report success at 100%) — test in Task 1.

---

### Task 1: Upload progress in the API layer

**Files:**
- Modify: `web/src/api/documents.ts` (the `uploadPdf` function at the end of the upload section)
- Test: `web/src/api/documents.test.ts` (the `describe("uploadPdf")` block)

**Interfaces:**
- Produces:
  - `export type UploadEvents = { onStarted?: (documentId: string) => void; onProgress?: (fraction: number) => void };`
  - `export type PostForm = (url: string, form: FormData, onProgress: (fraction: number) => void) => Promise<number>;` (resolves with the HTTP status)
  - `export function postForm(url: string, form: FormData, onProgress: (fraction: number) => void): Promise<number>`
  - `export async function uploadPdf(file: File, events: UploadEvents = {}, apiClient: Client = client, post: PostForm = postForm): Promise<void>` — calls `onStarted` with the new document id after the presign, `onProgress` with 0..1 during the send and `1` on success; rejects on a non-2xx status.

- [ ] **Step 1: Write the failing tests** — replace the `describe("uploadPdf")` block in `web/src/api/documents.test.ts` and add a `describe("postForm")` block; add `postForm` to the import list from `./documents` and `afterEach` to the vitest import.

```ts
describe("uploadPdf", () => {
  const started = { document_id: "d1", upload_id: "u1", url: "http://s3.test/bucket", fields: { key: "uploads/ada/u1.pdf", policy: "p" } };

  it("asks for a presigned POST with the file name, then posts the fields and the file last", async () => {
    const { apiClient, fetch } = api(() => json(started, 201));
    const post = vi.fn(async () => 204);
    const file = new File(["%PDF"], "paper.pdf", { type: "application/pdf" });

    await uploadPdf(file, {}, apiClient, post);

    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.url).toBe("http://api.test/uploads");
    expect(await request.json()).toEqual({ file_name: "paper.pdf" });
    const [url, form] = post.mock.calls[0]! as unknown as [string, FormData];
    expect(url).toBe("http://s3.test/bucket");
    expect([...form.keys()]).toEqual(["key", "policy", "file"]);
    expect(form.get("file")).toBe(file);
  });

  it("reports the new document id, then the progress, then 1 when storage accepts the file", async () => {
    const { apiClient } = api(() => json(started, 201));
    const seen: string[] = [];
    const post = vi.fn(async (_url: string, _form: FormData, onProgress: (f: number) => void) => {
      onProgress(0.5);
      return 204;
    });
    await uploadPdf(new File(["%PDF"], "p.pdf"), { onStarted: (id) => seen.push(`started ${id}`), onProgress: (f) => seen.push(`progress ${f}`) }, apiClient, post);
    expect(seen).toEqual(["started d1", "progress 0.5", "progress 1"]);
  });

  it("rejects when S3 refuses the file, and never reports 1", async () => {
    const { apiClient } = api(() => json(started, 201));
    const onProgress = vi.fn();
    await expect(uploadPdf(new File(["x"], "x.pdf"), { onProgress }, apiClient, async () => 403)).rejects.toThrow("403");
    expect(onProgress).not.toHaveBeenCalledWith(1);
  });
});

describe("postForm", () => {
  class FakeXhr {
    static last: FakeXhr;
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = 0;
    method = "";
    url = "";
    body: unknown = null;
    constructor() {
      FakeXhr.last = this;
    }
    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }
    send(body: unknown) {
      this.body = body;
    }
  }

  afterEach(() => vi.unstubAllGlobals());

  it("posts the form and reports the fraction sent, then resolves with the status", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const form = new FormData();
    const onProgress = vi.fn();
    const sent = postForm("http://s3.test/bucket", form, onProgress);
    const xhr = FakeXhr.last;
    expect([xhr.method, xhr.url, xhr.body]).toEqual(["POST", "http://s3.test/bucket", form]);
    xhr.upload.onprogress!({ lengthComputable: true, loaded: 25, total: 100 });
    xhr.upload.onprogress!({ lengthComputable: false, loaded: 0, total: 0 });
    xhr.status = 204;
    xhr.onload!();
    await expect(sent).resolves.toBe(204);
    expect(onProgress.mock.calls).toEqual([[0.25]]);
  });

  it("rejects on a network error", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const sent = postForm("http://s3.test/bucket", new FormData(), vi.fn());
    FakeXhr.last.onerror!();
    await expect(sent).rejects.toThrow("Upload to storage failed");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run src/api/documents.test.ts`
Expected: FAIL — `postForm` is not exported; `uploadPdf` posts with `fetch`.

- [ ] **Step 3: Implement** — replace `uploadPdf` in `web/src/api/documents.ts` with:

```ts
export type UploadEvents = { onStarted?: (documentId: string) => void; onProgress?: (fraction: number) => void };
export type PostForm = (url: string, form: FormData, onProgress: (fraction: number) => void) => Promise<number>;

// fetch can't report upload progress; XMLHttpRequest can (the upload tray's bars). Resolves with the HTTP status.
export function postForm(url: string, form: FormData, onProgress: (fraction: number) => void): Promise<number> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => resolve(xhr.status);
    xhr.onerror = () => reject(new Error("Upload to storage failed (network error)"));
    xhr.onabort = () => reject(new Error("Upload to storage failed (aborted)"));
    xhr.send(form);
  });
}

// The API presigns a POST for this learner's key and creates the row; the browser then sends the file straight to S3 (PRD §9.3).
// Callers check the file first with rejectionReason.
export async function uploadPdf(file: File, events: UploadEvents = {}, apiClient: Client = client, post: PostForm = postForm): Promise<void> {
  const { data, error, response } = await startUpload({ client: apiClient, body: { file_name: file.name }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`POST /uploads failed (${response?.status ?? "no response"})`);
  events.onStarted?.(data.document_id);
  const form = new FormData();
  for (const [name, value] of Object.entries(data.fields)) form.append(name, value);
  form.append("file", file); // S3 ignores fields after the file
  const status = await post(data.url, form, (fraction) => events.onProgress?.(fraction));
  if (status < 200 || status >= 300) throw new Error(`Upload to storage failed (${status})`);
  events.onProgress?.(1);
}
```

`LibraryPage.tsx` has `const defaultUpload = (file: File) => uploadPdf(file);` — it still compiles (events default to `{}`); Task 4 changes it.

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npx vitest run src/api/documents.test.ts && npx tsc -b`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/documents.ts web/src/api/documents.test.ts
git commit -m "Report upload progress and the new document id from uploadPdf"
```

---

### Task 2: UploadTray component and the "Uploading" badge

**Files:**
- Modify: `web/src/components/StateBadge/StateBadge.tsx`, `StateBadge.module.css`, `StateBadge.test.tsx`
- Create: `web/src/components/UploadTray/UploadTray.tsx`, `UploadTray.module.css`, `UploadTray.test.tsx`

**Interfaces:**
- Produces:
  - `StateBadge` accepts `state: "uploading"` (label "Uploading", `Upload` icon, the processing look).
  - `export type TrayItem = { id: string; name: string; size: string; status: "uploading" | "uploaded" | "failed"; progress: number };` (`size` is preformatted, e.g. `"0.9 MB"`; `progress` 0..1)
  - `export function UploadTray({ items, onClose }: { items: TrayItem[]; onClose: () => void })` — renders nothing for an empty list; items render in the given order.

- [ ] **Step 1: Write the failing tests**

In `StateBadge.test.tsx` add `["uploading", "Uploading"],` to the `it.each` table.

Create `web/src/components/UploadTray/UploadTray.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UploadTray, type TrayItem } from "./UploadTray";

const uploading: TrayItem = { id: "1", name: "lewis-rag-2020.pdf", size: "0.9 MB", status: "uploading", progress: 0.42 };
const uploaded: TrayItem = { id: "2", name: "react-yao-2022.pdf", size: "3.1 MB", status: "uploaded", progress: 1 };
const failed: TrayItem = { id: "3", name: "big.pdf", size: "2.2 MB", status: "failed", progress: 0.3 };

describe("UploadTray", () => {
  it("renders nothing without items", () => {
    const { container } = render(<UploadTray items={[]} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a labelled progress bar for each uploading file and no Close while busy", () => {
    render(<UploadTray items={[uploading, { ...uploading, id: "4", name: "b.pdf", progress: 0 }]} onClose={vi.fn()} />);
    const tray = screen.getByRole("region", { name: "Uploading 2 files…" });
    const bar = within(tray).getByRole("progressbar", { name: "Upload progress for lewis-rag-2020.pdf" });
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(within(tray).getByText("Uploading · 0.9 MB")).toBeVisible();
    expect(within(tray).getAllByRole("progressbar")).toHaveLength(2);
    expect(within(tray).queryByRole("button", { name: "Close uploads" })).toBeNull();
  });

  it("counts only uploading files in the busy header, singular for one", () => {
    render(<UploadTray items={[uploading, uploaded]} onClose={vi.fn()} />);
    expect(screen.getByRole("region", { name: "Uploading 1 file…" })).toBeVisible();
  });

  it("says uploaded or failed when done, and offers Close", async () => {
    const onClose = vi.fn();
    render(<UploadTray items={[uploaded, failed]} onClose={onClose} />);
    const tray = screen.getByRole("region", { name: "Uploads · 2 files" });
    expect(within(tray).getByText("Uploaded · processing")).toBeVisible();
    expect(within(tray).getByText("Upload failed")).toBeVisible();
    expect(within(tray).queryByRole("progressbar")).toBeNull();
    await userEvent.click(within(tray).getByRole("button", { name: "Close uploads" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("collapses and expands the list by keyboard", async () => {
    render(<UploadTray items={[uploaded]} onClose={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: "Collapse uploads" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    toggle.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByText("react-yao-2022.pdf")).toBeNull();
    const expand = screen.getByRole("button", { name: "Expand uploads" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(expand).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("react-yao-2022.pdf")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run src/components/StateBadge src/components/UploadTray`
Expected: FAIL — `UploadTray` module not found; no "uploading" badge.

- [ ] **Step 3: Implement**

`StateBadge.tsx`: import `Upload` from `lucide-react`; change the type and table:

```tsx
// Release 1 states, plus "uploading" while the browser still sends the file; "archived" arrives with its story (DESIGN.md → Document states).
export type DocumentState = "uploading" | "processing" | "awaiting_subjects" | "ready" | "failed";

const LOOK: Record<DocumentState, { label: string; icon: LucideIcon }> = {
  uploading: { label: "Uploading", icon: Upload },
  processing: { label: "Processing", icon: LoaderCircle },
  ...
```

`StateBadge.module.css`: change `.processing { … }` to `.uploading, .processing { background: var(--surface-2); color: var(--text-2); }` (the spin rule stays on `.processing .icon` only).

`web/src/components/UploadTray/UploadTray.tsx`:

```tsx
import { ChevronDown, ChevronUp, CircleAlert, CircleCheck, FileText, X } from "lucide-react";
import { useId, useState } from "react";

import styles from "./UploadTray.module.css";

export type TrayItem = { id: string; name: string; size: string; status: "uploading" | "uploaded" | "failed"; progress: number };

const files = (n: number) => `${n} ${n === 1 ? "file" : "files"}`;

// Fixed bottom right and non-blocking (DESIGN.md → Layout). Results are announced by the page's live region, not here.
export function UploadTray({ items, onClose }: { items: TrayItem[]; onClose: () => void }) {
  const headingId = useId();
  const [collapsed, setCollapsed] = useState(false);
  if (!items.length) return null;
  const busy = items.filter((t) => t.status === "uploading").length;
  const Toggle = collapsed ? ChevronUp : ChevronDown;
  return (
    <section className={styles.tray} aria-labelledby={headingId}>
      <div className={styles.head}>
        <strong id={headingId} className={styles.heading}>
          {busy ? `Uploading ${files(busy)}…` : `Uploads · ${files(items.length)}`}
        </strong>
        <button type="button" className={styles.iconButton} aria-expanded={!collapsed} aria-label={collapsed ? "Expand uploads" : "Collapse uploads"} onClick={() => setCollapsed((c) => !c)}>
          <Toggle strokeWidth={1.5} aria-hidden="true" />
        </button>
        {!busy && (
          <button type="button" className={styles.iconButton} aria-label="Close uploads" onClick={onClose}>
            <X strokeWidth={1.5} aria-hidden="true" />
          </button>
        )}
      </div>
      {!collapsed && (
        <ul className={styles.list}>
          {items.map((t) => (
            <TrayRow key={t.id} item={t} />
          ))}
        </ul>
      )}
    </section>
  );
}

function TrayRow({ item }: { item: TrayItem }) {
  const Icon = item.status === "uploaded" ? CircleCheck : item.status === "failed" ? CircleAlert : FileText;
  const status = item.status === "uploading" ? `Uploading · ${item.size}` : item.status === "uploaded" ? "Uploaded · processing" : "Upload failed";
  const percent = Math.round(item.progress * 100);
  return (
    <li className={`${styles.item} ${styles[item.status]}`}>
      <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      <div className={styles.text}>
        <span className={styles.name}>{item.name}</span>
        <span className={styles.status}>{status}</span>
        {item.status === "uploading" && (
          <div className={styles.bar} role="progressbar" aria-label={`Upload progress for ${item.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
            <span style={{ transform: `scaleX(${item.progress})` }} />
          </div>
        )}
      </div>
    </li>
  );
}
```

`web/src/components/UploadTray/UploadTray.module.css` (port of prototype `.tray`, `.tray-head`, `.tray-item`, `.bar`):

```css
.tray {
  position: fixed; right: var(--sp-6); bottom: var(--sp-6); z-index: 46; width: var(--tray-w);
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); box-shadow: var(--shadow-lg);
  overflow: hidden; animation: rise-in var(--dur-base) var(--ease-out);
}
.head {
  display: flex; align-items: center; gap: var(--sp-2); padding: var(--sp-2) var(--sp-2) var(--sp-2) var(--sp-4);
  background: var(--surface-2); border-bottom: 1px solid var(--border);
}
.heading { flex: 1 1 0; font-size: var(--fs-14); }
.iconButton {
  display: grid; place-items: center; width: 32px; height: 32px; flex: none; border: 1px solid transparent;
  border-radius: var(--r-sm); background: transparent; color: var(--text-2);
}
.iconButton:hover { background: var(--surface-3); color: var(--text); }
.iconButton svg { width: 16px; height: 16px; }
.list { margin: 0; padding: 0; list-style: none; max-height: 320px; overflow-y: auto; }
.item {
  display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border);
}
.item:last-child { border-bottom: 0; }
.icon { width: 20px; height: 20px; margin-top: 2px; color: var(--text-2); }
.uploaded .icon { color: var(--success); }
.failed .icon { color: var(--danger); }
.text { display: grid; min-width: 0; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-14); font-weight: 600; }
.status { font-size: var(--fs-14); color: var(--text-2); }
.failed .status { color: var(--danger); }
.bar { height: 6px; margin-top: 6px; border-radius: var(--r-pill); background: var(--surface-3); overflow: hidden; }
.bar > span {
  display: block; width: 100%; height: 100%; border-radius: inherit; background: var(--accent);
  transform-origin: left; transition: transform var(--dur-base) var(--ease-out);
}

@keyframes rise-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npx vitest run src/components/StateBadge src/components/UploadTray && npx tsc -b`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/StateBadge web/src/components/UploadTray
git commit -m "Add the upload tray component and an Uploading badge"
```

---

### Task 3: Page-wide drop zone hook and overlay

**Files:**
- Create: `web/src/features/library/usePageDrop.ts`, `web/src/features/library/usePageDrop.test.tsx`, `web/src/features/library/DropOverlay.tsx`, `web/src/features/library/DropOverlay.module.css`

**Interfaces:**
- Produces:
  - `export function usePageDrop(onFiles: (files: File[]) => void): boolean` — `true` while files are dragged over the document; listens on `document` only while the calling component is mounted; ignores drags that carry no files.
  - `export function DropOverlay()` — the `aria-hidden` "Drop PDFs to upload" overlay (render it only when the hook returns `true`).

- [ ] **Step 1: Write the failing test** — `web/src/features/library/usePageDrop.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DropOverlay } from "./DropOverlay";
import { usePageDrop } from "./usePageDrop";

function Page({ onFiles }: { onFiles: (files: File[]) => void }) {
  const active = usePageDrop(onFiles);
  return (
    <div>
      <p>Library</p>
      {active && <DropOverlay />}
    </div>
  );
}

const withFiles = (files: File[] = []) => ({ dataTransfer: { types: ["Files"], files } });
const textOnly = { dataTransfer: { types: ["text/plain"], files: [] } };

describe("usePageDrop", () => {
  it("highlights the page while files are dragged over it and clears on leave", () => {
    render(<Page onFiles={vi.fn()} />);
    fireEvent.dragEnter(document.body, withFiles());
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    fireEvent.dragLeave(document.body, withFiles());
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("stays highlighted while the drag moves between child elements", () => {
    render(<Page onFiles={vi.fn()} />);
    const child = screen.getByText("Library");
    fireEvent.dragEnter(document.body, withFiles());
    fireEvent.dragEnter(child, withFiles());
    fireEvent.dragLeave(document.body, withFiles());
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    fireEvent.dragLeave(child, withFiles());
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("hands the dropped files over and clears the highlight", () => {
    const onFiles = vi.fn();
    render(<Page onFiles={onFiles} />);
    const a = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    const b = new File(["x"], "b.docx");
    fireEvent.dragEnter(document.body, withFiles());
    const drop = fireEvent.drop(document.body, withFiles([a, b]));
    expect(drop).toBe(false); // default prevented: the browser must not open the file
    expect(onFiles).toHaveBeenCalledWith([a, b]);
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("prevents the default on drag-over so the page accepts the drop", () => {
    render(<Page onFiles={vi.fn()} />);
    expect(fireEvent.dragOver(document.body, withFiles())).toBe(false);
  });

  it("ignores drags without files", () => {
    const onFiles = vi.fn();
    render(<Page onFiles={onFiles} />);
    fireEvent.dragEnter(document.body, textOnly);
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
    expect(fireEvent.drop(document.body, textOnly)).toBe(true);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("stops listening when the page unmounts", () => {
    const onFiles = vi.fn();
    const { unmount } = render(<Page onFiles={onFiles} />);
    unmount();
    expect(fireEvent.drop(document.body, withFiles([new File(["%PDF"], "a.pdf")]))).toBe(true);
    expect(onFiles).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run src/features/library/usePageDrop.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`web/src/features/library/usePageDrop.ts`:

```ts
import { useEffect, useRef, useState } from "react";

const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");

// The whole page accepts dropped files while the Library is mounted (brief §6.3). Dragging over child elements fires
// dragenter/dragleave pairs, so a depth count decides when the drag has really left. Drags without files are left alone.
export function usePageDrop(onFiles: (files: File[]) => void): boolean {
  const [active, setActive] = useState(false);
  const onFilesRef = useRef(onFiles);
  useEffect(() => {
    onFilesRef.current = onFiles;
  }, [onFiles]);

  useEffect(() => {
    let depth = 0;
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth++;
      setActive(true);
    };
    const over = (event: DragEvent) => {
      if (carriesFiles(event)) event.preventDefault();
    };
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setActive(false);
    };
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setActive(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length) onFilesRef.current(files);
    };
    document.addEventListener("dragenter", enter);
    document.addEventListener("dragover", over);
    document.addEventListener("dragleave", leave);
    document.addEventListener("drop", drop);
    return () => {
      document.removeEventListener("dragenter", enter);
      document.removeEventListener("dragover", over);
      document.removeEventListener("dragleave", leave);
      document.removeEventListener("drop", drop);
    };
  }, []);

  return active;
}
```

`web/src/features/library/DropOverlay.tsx`:

```tsx
import { Upload } from "lucide-react";

import styles from "./DropOverlay.module.css";

// Visual only: the keyboard path is the Upload button, and the drop result is announced by the page's live region.
export function DropOverlay() {
  return (
    <div className={styles.overlay} aria-hidden="true">
      <div className={styles.label}>
        <Upload className={styles.icon} strokeWidth={1.5} />
        Drop PDFs to upload
      </div>
    </div>
  );
}
```

`web/src/features/library/DropOverlay.module.css` (port of prototype `.drop-overlay`; the prototype's `--review-h` offset is review chrome and is dropped):

```css
.overlay {
  position: fixed; top: 0; right: 0; bottom: 0; left: var(--nav-w); z-index: 44;
  display: grid; place-items: center; pointer-events: none;
  background: color-mix(in oklab, var(--accent-soft) 88%, transparent); border: 3px dashed var(--accent);
  animation: fade-in var(--dur-fast) var(--ease-out);
}
.label {
  display: grid; justify-items: center; gap: var(--sp-2);
  color: var(--accent-text); font-family: var(--font-display); font-size: var(--fs-32); font-weight: 600;
}
.icon { width: 28px; height: 28px; }

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run src/features/library/usePageDrop.test.tsx && npx tsc -b`
Expected: PASS. (If jsdom's `fireEvent` doesn't attach `dataTransfer`, Testing Library defines it from the event init for drag events; keep the `{ dataTransfer: {...} }` init shape.)

- [ ] **Step 5: Commit**

```bash
git add web/src/features/library/usePageDrop.ts web/src/features/library/usePageDrop.test.tsx web/src/features/library/DropOverlay.tsx web/src/features/library/DropOverlay.module.css
git commit -m "Accept files dropped anywhere on the Library page"
```

---

### Task 4: Library uploads in parallel with the tray, drop zone and Uploading rows

**Files:**
- Modify: `web/src/features/library/LibraryPage.tsx`, `web/src/features/library/DocumentTable.tsx`, `web/src/features/library/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `uploadPdf(file, events)`, `UploadEvents`, `megabytes` (Task 1, `api/documents`); `UploadTray`, `TrayItem` (Task 2); `StateBadge state="uploading"` (Task 2); `usePageDrop`, `DropOverlay` (Task 3).
- Produces:
  - `LibraryPage` prop `upload?: (file: File, events: UploadEvents) => Promise<void>` (was `(file: File) => Promise<void>`).
  - `DocumentTable` prop `uploading?: ReadonlySet<string>` — document ids whose file is still being sent; those rows show the "Uploading" badge and no processing hints.

Behavior for one batch (picked or dropped), each file concurrently:
1. Not a PDF / empty / too big → the existing "Files not uploaded" list and status part (unchanged wording).
2. `check(file)` finds it → the existing "Already in your library" list (unchanged).
3. Otherwise a tray item is added **at the top** (`status: "uploading"`, `progress: 0`), `upload(file, { onStarted, onProgress })` runs; `onStarted(id)` adds the id to `uploading` and refreshes the list (the row appears with "Uploading"); `onProgress` updates the item; success → item `uploaded`, status part `Uploaded {name}. Processing.`; failure → item `failed`, status part `Upload failed: {name}.` and a "Couldn't upload {name}. Try again." paragraph (one per failed file). The id leaves `uploading` either way, then the list refreshes.
4. The status region shows the parts in pick order, with `Checking {name}…` / `Uploading {name}…` while a file is in flight. Session expiry during the check stops that file only.

- [ ] **Step 1: Update existing tests and write the failing ones** in `web/src/features/library/LibraryPage.test.tsx`:

Change the imports to:

```tsx
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
...
import { RetriesUsedUpError, type DocumentResponse, type UploadEvents } from "../../api/documents";
```

In "uploads the picked PDF and refreshes the list" replace `expect(upload).toHaveBeenCalledWith(file);` with `expect(upload).toHaveBeenCalledWith(file, expect.any(Object));`. Do the same for `toHaveBeenCalledWith(good)` (→ `(good, expect.any(Object))`), `toHaveBeenCalledWith(fresh)` and `toHaveBeenCalledWith(file)` in "uploads anyway when the check fails".

Add this `describe` block after the `describe("LibraryPage")` block:

```tsx
describe("LibraryPage drop zone and upload tray", () => {
  const pdf = (name: string) => new File(["%PDF"], name, { type: "application/pdf" });
  const drop = (files: File[]) => {
    fireEvent.dragEnter(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    fireEvent.drop(document.body, { dataTransfer: { types: ["Files"], files } });
  };

  // An upload that waits until the test settles it, so the tray can be seen mid-flight.
  function controlledUpload() {
    const pending = new Map<string, { events: UploadEvents; resolve: () => void; reject: (e: Error) => void }>();
    const upload = vi.fn(
      (file: File, events: UploadEvents) =>
        new Promise<void>((resolve, reject) => {
          pending.set(file.name, { events, resolve, reject });
        }),
    );
    return { upload, pending };
  }

  it("highlights the page on drag-over and clears it on drag-leave", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
    await screen.findByText("Upload your first document");
    fireEvent.dragEnter(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.getByText("Drop PDFs to upload")).toBeInTheDocument();
    fireEvent.dragLeave(document.body, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
  });

  it("uploads three dropped PDFs in parallel, each with its own progress bar", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")]);
    expect(screen.queryByText("Drop PDFs to upload")).toBeNull();
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3)); // all three started before any finished
    const tray = screen.getByRole("region", { name: "Uploading 3 files…" });
    act(() => pending.get("b.pdf")!.events.onProgress!(0.5));
    expect(within(tray).getByRole("progressbar", { name: "Upload progress for b.pdf" })).toHaveAttribute("aria-valuenow", "50");
    expect(within(tray).getAllByRole("progressbar")).toHaveLength(3);
    await act(async () => {
      for (const p of pending.values()) p.resolve();
    });
    expect(await screen.findByRole("region", { name: "Uploads · 3 files" })).toBeVisible();
    expect(within(screen.getByRole("region", { name: "Uploads · 3 files" })).getAllByText("Uploaded · processing")).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("Uploaded a.pdf. Processing. Uploaded b.pdf. Processing. Uploaded c.pdf. Processing.");
  });

  it("refuses a dropped non-PDF the same way as a picked one", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([new File(["x"], "reading-list.docx", { type: "application/msword" }), pdf("paper.pdf")]);
    const list = await screen.findByRole("list", { name: "Files not uploaded" });
    expect(within(list).getByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect((upload.mock.calls[0] as unknown as [File])[0].name).toBe("paper.pdf");
  });

  it("keeps the other uploads going when one fails", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf"), pdf("b.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    await act(async () => pending.get("a.pdf")!.reject(new Error("Upload to storage failed (403)")));
    const tray = screen.getByRole("region", { name: "Uploading 1 file…" });
    expect(within(tray).getByText("Upload failed")).toBeVisible();
    expect(within(tray).getByRole("progressbar", { name: "Upload progress for b.pdf" })).toBeVisible();
    await act(async () => pending.get("b.pdf")!.resolve());
    expect(await screen.findByText("Couldn't upload a.pdf. Try again.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Upload failed: a.pdf. Uploaded b.pdf. Processing.");
  });

  it("adds a second drop to the same tray, newest first, and hides Close until all finish", async () => {
    const { upload, pending } = controlledUpload();
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("first.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    drop([pdf("second.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    const tray = screen.getByRole("region", { name: "Uploading 2 files…" });
    expect(within(tray).getAllByRole("listitem").map((li) => li.textContent)).toEqual([expect.stringContaining("second.pdf"), expect.stringContaining("first.pdf")]);
    await act(async () => pending.get("first.pdf")!.resolve());
    expect(within(tray).queryByRole("button", { name: "Close uploads" })).toBeNull();
    await act(async () => pending.get("second.pdf")!.resolve());
    await userEvent.click(await screen.findByRole("button", { name: "Close uploads" }));
    expect(screen.queryByRole("region", { name: /Uploads/ })).toBeNull();
  });

  it("shows the new row as Uploading until its file reaches storage, then Processing", async () => {
    const { upload, pending } = controlledUpload();
    const row: DocumentResponse = { ...processing, document_id: "d9", title: "a.pdf" };
    const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([row]);
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={load} upload={upload} />);
    await screen.findByText("Upload your first document");
    drop([pdf("a.pdf")]);
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    act(() => pending.get("a.pdf")!.events.onStarted!("d9"));
    const tr = (await screen.findByRole("cell", { name: /a\.pdf/ })).closest("tr")!;
    expect(within(tr).getByText("Uploading")).toBeVisible();
    expect(within(tr).queryByText("You can choose subjects when processing finishes.")).toBeNull();
    await act(async () => pending.get("a.pdf")!.resolve());
    expect(await within(tr).findByText("Processing")).toBeVisible();
  });

  it("uploads by keyboard from the Upload button", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => [processing]} upload={upload} />);
    const button = await screen.findByRole("button", { name: "Upload" });
    const input = screen.getByLabelText("Upload PDFs") as HTMLInputElement;
    const click = vi.spyOn(input, "click");
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(click).toHaveBeenCalled();
  });

  it("tells the learner they can drop files in the first-run card", async () => {
    render(<LibraryPage check={notInLibrary} loadLimits={limits} load={async () => []} upload={vi.fn()} />);
    expect(await screen.findByText("Or drop files anywhere on this page. You can add several at once.")).toBeVisible();
  });
});
```

Note: `drop()` fires on `document.body`; the hook's listeners are on `document`, so the events bubble there.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd web && npx vitest run src/features/library/LibraryPage.test.tsx`
Expected: the new `drop zone and upload tray` tests FAIL (no overlay, no tray); the updated existing tests FAIL on `toHaveBeenCalledWith(file, expect.any(Object))`.

- [ ] **Step 3: Implement**

`DocumentTable.tsx`: add `uploading?: ReadonlySet<string>` to `Props` and destructure it with default `uploading = NONE` where `const NONE: ReadonlySet<string> = new Set();` is a module constant; change `StateCell` to take `uploading: boolean`:

```tsx
function StateCell({ doc, uploading }: { doc: DocumentResponse; uploading: boolean }) {
  // The API creates the row when it presigns the upload; until the browser has sent the file it reads "Uploading".
  if (uploading) return <StateBadge state="uploading" />;
  return (
    <>
      ...unchanged body...
    </>
  );
}
```

and render `<StateCell doc={doc} uploading={uploading.has(doc.document_id)} />`.

`LibraryPage.tsx`:

1. Imports: add `type UploadEvents` to the `../../api/documents` import; add `import { UploadTray, type TrayItem } from "../../components/UploadTray/UploadTray";`, `import { DropOverlay } from "./DropOverlay";`, `import { usePageDrop } from "./usePageDrop";`. `ChangeEvent` stays.
2. Props: `upload?: (file: File, events: UploadEvents) => Promise<void>;` and `const defaultUpload = (file: File, events: UploadEvents) => uploadPdf(file, events);`.
3. Replace the header comment `// Library with a plain file picker (US-2 first slice). Drop zone, upload tray, tabs and filters come later.` with `// Library: upload by picking or dropping PDFs (US-2), the upload tray, and the document list. Tabs and filters come later.`
4. State: replace `const [failed, setFailed] = useState<string | null>(null);` with `const [failed, setFailed] = useState<string[]>([]);` and add:

```tsx
  const [tray, setTray] = useState<TrayItem[]>([]);
  const [uploading, setUploading] = useState<ReadonlySet<string>>(new Set()); // document ids whose file is still being sent
  const traySeq = useRef(0);
```

5. Replace `onPick` with `addFiles` plus a thin `onPick`, and wire the drop hook:

```tsx
  const updateTray = (id: string, patch: Partial<TrayItem>) => setTray((items) => items.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  const setSending = (documentId: string, sending: boolean) =>
    setUploading((ids) => {
      const next = new Set(ids);
      if (sending) next.add(documentId);
      else next.delete(documentId);
      return next;
    });

  // Every file of a pick or drop runs at once. One combined message in pick order, so no file's result overwrites another's in the live region.
  async function addFiles(files: File[]) {
    setFailed([]);
    setRejected([]);
    setAlreadyIn([]);
    const current = limits ?? (await ensureLimits());
    const parts: string[] = files.map(() => "");
    const say = () => setStatus(parts.filter(Boolean).join(" "));

    async function one(file: File, i: number) {
      const reason = rejectionReason(file, current);
      if (reason) {
        setRejected((list) => [...list, { name: file.name, reason }]);
        parts[i] = `${file.name}: ${reason}`;
        say();
        return;
      }
      parts[i] = `Checking ${file.name}…`;
      say();
      let existing: string | null = null;
      try {
        existing = await check(file);
      } catch (error) {
        if (error instanceof SessionExpiredError) return; // the session screen replaces this page
        // Any other failure: upload anyway; the server-side hash decides (PRD D19).
      }
      if (existing) {
        const documentId = existing;
        setAlreadyIn((list) => [...list, { name: file.name, documentId }]);
        parts[i] = `${file.name}: Already in your library.`;
        say();
        return;
      }
      parts[i] = `Uploading ${file.name}…`;
      say();
      const id = `upload-${++traySeq.current}`;
      setTray((items) => [{ id, name: file.name, size: `${megabytes(file.size)} MB`, status: "uploading", progress: 0 }, ...items]);
      const started: { documentId?: string } = {};
      try {
        if (!current) throw new Error("Upload limits unavailable");
        await upload(file, {
          onStarted: (documentId) => {
            started.documentId = documentId;
            setSending(documentId, true);
            void refresh();
          },
          onProgress: (progress) => updateTray(id, { progress }),
        });
        updateTray(id, { status: "uploaded", progress: 1 });
        parts[i] = `Uploaded ${file.name}. Processing.`;
      } catch {
        // A 401 is handled by the API client: the session screen replaces this page.
        updateTray(id, { status: "failed" });
        parts[i] = `Upload failed: ${file.name}.`;
        setFailed((names) => [...names, file.name]);
      }
      if (started.documentId) setSending(started.documentId, false);
      say();
      await refresh();
    }

    await Promise.all(files.map((file, i) => one(file, i)));
  }

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = ""; // picking the same file again fires change again
    if (files.length) void addFiles(files);
  }

  const dragging = usePageDrop((files) => void addFiles(files));

  function closeTray() {
    setTray([]);
    document.getElementById("main-content")?.focus(); // the Close button is gone
  }
```

6. JSX: change the input's handler to `onChange={onPick}`; replace the single `failed` paragraph with

```tsx
      {failed.map((name, i) => (
        <p key={`${name}-${i}`} className={styles.error}>
          Couldn't upload {name}. Try again.
        </p>
      ))}
```

change the first-run card's `note` to `note="Or drop files anywhere on this page. You can add several at once."`; pass `uploading={uploading}` to `DocumentTable`; and add at the end of the fragment:

```tsx
      {dragging && <DropOverlay />}
      <UploadTray items={tray} onClose={closeTray} />
```

- [ ] **Step 4: Run all web tests and the build**

Run: `cd web && npm test && npm run build`
Expected: all tests PASS (including the existing LibraryPage, SubjectPicker and retry tests), build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/library
git commit -m "Upload dropped or picked PDFs in parallel with a progress tray"
```

---

### After the tasks (controller, not a subagent task)

- Visual check against `library-drop-active` and `library-uploading` at 1440px and 1280px, light and dark: run the app (`docker compose up -d` + `make api`/`make web`, or the app profile), sign in as `learner@example.com`, drag files / upload three PDFs, screenshot with Playwright, compare with `.design-shots/v0.4/`.
- PR description: closes #65; records the `library-first-processing` gap (rows keep the file name as title until US-2b's first-pages step exists); notes that the tray lives on the Library page (DESIGN.md says "on every screen" — moving upload state to the app shell is a follow-up); rejected and duplicate files stay in the existing page lists rather than the tray (brief §6.3 puts them in the tray; earlier slices own that wording).
