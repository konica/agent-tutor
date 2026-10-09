import { AlertCircle, Archive, Filter, Info, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import { SessionExpiredError } from "../../auth/authClient";
import { archiveDocument, deleteDocument, DocumentGoneError, DocumentProcessingError, findInLibrary, loadDocumentDetails, loadDocuments, loadSubjectSuggestions, loadUploadLimits, loadUploadStatus, megabytes, rejectionReason, restoreDocument, RetriesUsedUpError, retryProcessing, saveDocumentTitle, saveSubjects as saveChosenSubjects, uploadPdf, type DocumentDetails, type DocumentFilters, type DocumentResponse, type SubjectSuggestions, type UploadEvents, type UploadLimits, type UploadStatus } from "../../api/documents";
import type { SubjectResponse } from "../../api/generated/types.gen";
import { loadMySubjects } from "../../api/subjects";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { Tabs } from "../../components/Tabs/Tabs";
import { UploadTray, type TrayItem } from "../../components/UploadTray/UploadTray";
import { DeleteDialog } from "./DeleteDialog";
import { DocumentDetailsPanel } from "./DocumentDetails";
import { DocumentTable } from "./DocumentTable";
import { DropOverlay } from "./DropOverlay";
import { hasFilters, LibraryFilters } from "./LibraryFilters";
import { SubjectPicker, type PickerDocument } from "./SubjectPicker";
import styles from "./LibraryPage.module.css";
import { useDocuments } from "./useDocuments";
import { useLibraryCounts } from "./useLibraryCounts";
import { usePageDrop } from "./usePageDrop";

type Props = {
  load?: (filters: DocumentFilters) => Promise<DocumentResponse[]>;
  loadSubjects?: () => Promise<SubjectResponse[]>;
  upload?: (file: File, events: UploadEvents) => Promise<void>;
  retry?: (documentId: string) => Promise<void>;
  loadLimits?: () => Promise<UploadLimits>;
  check?: (file: File) => Promise<string | null>;
  loadSuggestions?: (documentId: string) => Promise<SubjectSuggestions>;
  saveSubjects?: (documentId: string, choice: { subject_ids: string[]; new_names: string[] }) => Promise<DocumentResponse>;
  loadUpload?: (uploadId: string) => Promise<UploadStatus>;
  archive?: (documentId: string) => Promise<DocumentResponse>;
  restore?: (documentId: string) => Promise<DocumentResponse>;
  loadDetails?: (documentId: string) => Promise<DocumentDetails>;
  saveTitle?: (documentId: string, title: string | null) => Promise<DocumentDetails>;
  remove?: (documentId: string) => Promise<void>;
  pollMs?: number;
};

type View = "active" | "archived";

const ARCHIVED_NOTICE = "Archived documents aren't used for answers, but citations to them in past conversations still work. Restore a document to change its subjects.";

function announceChange(doc: DocumentResponse): string | null {
  if (doc.state === "failed") return `${doc.title} failed${doc.failure_reason ? `: ${doc.failure_reason}` : ""}.`;
  if (doc.state === "awaiting_subjects") return `${doc.title} is ready to choose subjects.`;
  if (doc.state === "ready") return `${doc.title} is ready.`;
  return null;
}

const MAX_STATUS_POLLS = 150; // with the default 2 s poll, five minutes for the worker to hash the file
const MAX_PARALLEL_UPLOADS = 3; // each check hashes a whole file in memory, and presigned POSTs expire while queued behind the browser's connections

const defaultUpload = (file: File, events: UploadEvents) => uploadPdf(file, events);
const defaultRetry = (id: string) => retryProcessing(id);
const defaultLoadLimits = () => loadUploadLimits();
const defaultCheck = (file: File) => findInLibrary(file);
const defaultLoadUpload = (uploadId: string) => loadUploadStatus(uploadId);
const defaultArchive = (id: string) => archiveDocument(id);
const defaultRestore = (id: string) => restoreDocument(id);
const defaultLoadDetails = (id: string) => loadDocumentDetails(id);
const defaultSaveTitle = (id: string, title: string | null) => saveDocumentTitle(id, title);
const defaultRemove = (id: string) => deleteDocument(id);

const defaultLoadSubjects = () => loadMySubjects();
const defaultLoadSuggestions = (id: string) => loadSubjectSuggestions(id);
const defaultSaveSubjects = (id: string, choice: { subject_ids: string[]; new_names: string[] }) => saveChosenSubjects(id, choice);

// Library: upload by picking or dropping PDFs (US-2), the upload tray, and the Active and Archived lists narrowed by subject, upload dates and state (US-10).
export function LibraryPage({ load = loadDocuments, loadSubjects = defaultLoadSubjects, upload = defaultUpload, retry = defaultRetry, loadLimits = defaultLoadLimits, check = defaultCheck, loadSuggestions = defaultLoadSuggestions, saveSubjects = defaultSaveSubjects, loadUpload = defaultLoadUpload, archive = defaultArchive, restore = defaultRestore, loadDetails = defaultLoadDetails, saveTitle = defaultSaveTitle, remove = defaultRemove, pollMs = 2000 }: Props) {
  const [filters, setFilters] = useState<DocumentFilters>({});
  const [view, setView] = useState<View>("active");
  const archivedView = view === "archived";
  const { documents, applied, unavailable, refresh } = useDocuments(load, pollMs, archivedView ? { ...filters, archived: true } : filters);
  const counts = useLibraryCounts(load);
  // Until the selected tab's list arrives, the other tab's rows are not shown under it.
  const list = documents !== null && Boolean(applied.archived) === archivedView ? documents : null;
  // The empty states follow the filters the list was loaded with, so clearing never flashes the upload card before the full list arrives.
  const filtered = hasFilters(filters) || hasFilters(applied);
  const noActive = !archivedView && list?.length === 0 && !filtered;
  const firstRun = noActive && !counts.archived;
  const allArchived = noActive && Boolean(counts.archived);
  // The tabs stay while anything is archived, so an all-archived library can still reach its documents.
  const showToolbar = documents !== null && !firstRun;
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set()); // document ids whose archive or restore is running
  const [subjects, setSubjects] = useState<SubjectResponse[]>([]);
  const subjectSelect = useRef<HTMLSelectElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState<string[]>([]);
  const [tray, setTray] = useState<TrayItem[]>([]);
  const [uploading, setUploading] = useState<ReadonlySet<string>>(new Set()); // document ids whose file is still being sent
  const traySeq = useRef(0);
  const parts = useRef<string[]>([]); // one slot per file, shared by overlapping batches, so none overwrites another in the live region
  const inFlight = useRef(0); // batches still running
  const slots = useRef({ free: MAX_PARALLEL_UPLOADS, waiting: [] as (() => void)[] }); // upload slots shared by every batch
  const [retrying, setRetrying] = useState<ReadonlySet<string>>(new Set());
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const [alreadyIn, setAlreadyIn] = useState<{ name: string; documentId: string }[]>([]);
  const seen = useRef<Map<string, DocumentResponse["state"]> | null>(null);
  const justSaved = useRef(new Set<string>()); // saved here, so the poll must not announce "is ready." over "Subjects saved."
  const [picking, setPicking] = useState<PickerDocument | null>(null);
  const pickerFromDetails = useRef<string | null>(null); // the details panel to reopen when the picker closes
  const statusRegion = useRef<HTMLParagraphElement>(null);
  const wasPicking = useRef(false);
  const [details, setDetails] = useState<{ id: string; editing: boolean } | null>(null);
  const detailsOpener = useRef<string | null>(null); // the document whose details were last open
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [deleting, setDeleting] = useState<DocumentResponse | null>(null); // the document whose delete dialog is open
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | undefined>(undefined);
  const deleteDialog = useRef(0); // counts opened delete dialogs, so a late answer to a cancelled one is ignored
  const [deleted, setDeleted] = useState(false); // a delete just succeeded: its row, and the button that had focus, are going away

  // The dialog gives focus back to the More button as it unmounts, and the row then leaves; this effect runs after that, so the heading keeps focus.
  useEffect(() => {
    if (deleted && !deleting) {
      setDeleted(false);
      headingRef.current?.focus();
    }
  }, [deleted, deleting]);

  // The dialog gives focus back to the row button; after a save that button is gone, so the status region takes it.
  useEffect(() => {
    if (picking) wasPicking.current = true;
    else if (wasPicking.current) {
      wasPicking.current = false;
      if (document.activeElement === document.body || document.activeElement === null) statusRegion.current?.focus();
    }
  }, [picking]);

  // The panel gives focus back to its opener. When that was a menu item (gone now) or a row that left the list, fall back to the row's title, then the status region.
  useEffect(() => {
    if (details) {
      detailsOpener.current = details.id;
      return;
    }
    const id = detailsOpener.current;
    if (!id) return;
    detailsOpener.current = null;
    if (document.activeElement !== document.body && document.activeElement !== null) return;
    const title = document.querySelector<HTMLElement>(`#document-${id} td:first-child button`);
    (title ?? statusRegion.current)?.focus();
  }, [details]);

  function clearFilters() {
    setFilters({});
    subjectSelect.current?.focus(); // the Clear button disappears
  }

  async function onSaved(doc: DocumentResponse, changed: boolean) {
    justSaved.current.add(doc.document_id);
    seen.current?.set(doc.document_id, "ready");
    setStatus(changed ? `Subjects saved. ${doc.title} now uses ${doc.subjects.map((s) => s.name).join(", ")}.` : `Subjects saved. ${doc.title} is ready to use.`);
    await Promise.all([refresh(), refreshSubjects()]);
  }

  // From details, the picker replaces the panel (both are modal) and gives it back when it closes.
  function changeFromDetails(doc: DocumentDetails) {
    pickerFromDetails.current = doc.document_id;
    setDetails(null);
    setPicking(doc);
  }

  function closePicker() {
    setPicking(null);
    const back = pickerFromDetails.current;
    pickerFromDetails.current = null;
    if (back) setDetails({ id: back, editing: false });
  }

  // One polite live region carries upload results and processing-state changes (DESIGN.md → Accessibility).
  useEffect(() => {
    if (!documents) return;
    const before = seen.current;
    seen.current = new Map(documents.map((d) => [d.document_id, d.state]));
    if (!before) return; // the first load is not a change
    const changes = documents
      .filter((d) => !d.archived && before.has(d.document_id) && before.get(d.document_id) !== d.state && !justSaved.current.has(d.document_id))
      .map(announceChange)
      .filter((message): message is string => message !== null);
    for (const d of documents) if (d.state === "ready") justSaved.current.delete(d.document_id);
    if (changes.length) setStatus(changes.join(" "));
  }, [documents]);

  const loadLimitsRef = useRef(loadLimits);
  const alive = useRef(true);
  // The subject options are the learner's own; a failure keeps the previous options, and the filter still works by state and date.
  const loadSubjectsRef = useRef(loadSubjects);
  useEffect(() => {
    loadSubjectsRef.current = loadSubjects;
  }, [loadSubjects]);
  const refreshSubjects = useCallback(async () => {
    try {
      const loaded = await loadSubjectsRef.current();
      if (alive.current) setSubjects(loaded);
    } catch {
      // keep the previous options
    }
  }, []);
  useEffect(() => {
    void refreshSubjects();
  }, [refreshSubjects]);
  useEffect(() => {
    loadLimitsRef.current = loadLimits; // an inline `loadLimits` must not restart the load
  }, [loadLimits]);
  const loadUploadRef = useRef(loadUpload);
  useEffect(() => {
    loadUploadRef.current = loadUpload;
  }, [loadUpload]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const acquireSlot = () => {
    if (slots.current.free > 0) {
      slots.current.free--;
      return Promise.resolve();
    }
    return new Promise<void>((resolve) => slots.current.waiting.push(resolve));
  };
  const releaseSlot = () => {
    const next = slots.current.waiting.shift();
    if (next) next(); // the slot passes straight to the next file in line
    else slots.current.free++;
  };

  // Failure leaves the limits null: the pick handler retries, and never uploads without a size check.
  const ensureLimits = useCallback(async (): Promise<UploadLimits | null> => {
    try {
      const loaded = await loadLimitsRef.current();
      if (alive.current) setLimits(loaded);
      return loaded;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    void ensureLimits();
  }, [ensureLimits]);

  const updateTray = (id: string, patch: Partial<TrayItem>) => setTray((items) => items.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  const setSending = (documentId: string, sending: boolean) =>
    setUploading((ids) => {
      const next = new Set(ids);
      if (sending) next.add(documentId);
      else next.delete(documentId);
      return next;
    });

  // Files of a pick or drop run MAX_PARALLEL_UPLOADS at a time, across overlapping batches. One combined message in pick order; a batch that starts while another runs adds to it instead of resetting it.
  async function addFiles(files: File[]) {
    if (inFlight.current === 0) {
      parts.current = [];
      setFailed([]);
      setRejected([]);
      setAlreadyIn([]);
    }
    inFlight.current++;
    try {
      const current = limits ?? (await ensureLimits());
      const slots = files.map(() => parts.current.push("") - 1);
      const say = () => setStatus(parts.current.filter(Boolean).join(" "));
      await Promise.all(files.map((file, n) => one(file, slots[n], current, say)));
    } finally {
      inFlight.current--;
    }
  }

  async function one(file: File, i: number, current: UploadLimits | null, say: () => void) {
    const reason = rejectionReason(file, current);
    if (reason) {
      setRejected((list) => [...list, { name: file.name, reason }]);
      parts.current[i] = `${file.name}: ${reason}`;
      say();
      return;
    }
    parts.current[i] = `Checking ${file.name}…`;
    say();
    const id = `upload-${++traySeq.current}`;
    setTray((items) => [{ id, name: file.name, size: `${megabytes(file.size)} MB`, status: "uploading", progress: 0 }, ...items]);
    await acquireSlot();
    try {
      await send(file, i, id, current, say);
    } finally {
      releaseSlot();
    }
  }

  async function send(file: File, i: number, id: string, current: UploadLimits | null, say: () => void) {
    let existing: string | null = null;
    try {
      existing = await check(file);
    } catch (error) {
      if (error instanceof SessionExpiredError) return; // the session screen replaces this page
      // Any other failure: upload anyway; the server-side hash decides (PRD D19).
    }
    if (existing) {
      const documentId = existing;
      setTray((items) => items.filter((t) => t.id !== id));
      setAlreadyIn((list) => [...list, { name: file.name, documentId }]);
      parts.current[i] = `${file.name}: Already in your library.`;
      say();
      return;
    }
    parts.current[i] = `Uploading ${file.name}…`;
    say();
    const started: { documentId?: string; uploadId?: string } = {};
    try {
      if (!current) throw new Error("Upload limits unavailable");
      await upload(file, {
        onStarted: (documentId, uploadId) => {
          started.documentId = documentId;
          started.uploadId = uploadId;
          setSending(documentId, true);
          void refresh();
          void counts.refresh();
        },
        onProgress: (progress) => updateTray(id, { progress }),
      });
      updateTray(id, { status: "uploaded", progress: 1 });
      parts.current[i] = `Uploaded ${file.name}. Processing.`;
      if (started.uploadId) void watchUpload(id, started.uploadId, file.name);
    } catch {
      // A 401 is handled by the API client: the session screen replaces this page.
      updateTray(id, { status: "failed" });
      parts.current[i] = `Upload failed: ${file.name}.`;
      setFailed((names) => [...names, file.name]);
    }
    if (started.documentId) setSending(started.documentId, false);
    say();
    await refresh();
  }

  // The worker decides duplicates by the server hash (PRD D19); a duplicate's placeholder document disappears, so ask the upload.
  // The answer can come after a newer batch reused this file's live-region slot, so it is announced on its own.
  async function watchUpload(trayId: string, uploadId: string, name: string) {
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
      if (found.outcome === "duplicate") {
        // Without a document id the row still says "Already in your library", just with no link.
        updateTray(trayId, { status: "already", documentId: found.document_id ?? undefined, archived: found.archived });
        setStatus(`${name}: Already in your library${found.archived ? ", archived" : ""}.`);
        await Promise.all([refresh(), counts.refresh()]);
      }
      return;
    }
  }

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = ""; // picking the same file again fires change again
    if (files.length) void addFiles(files);
  }

  const dragging = usePageDrop((files) => {
    if (!picking && !details) void addFiles(files); // the dialogs are modal
  });

  function closeTray() {
    setTray([]);
    document.getElementById("main-content")?.focus(); // the Close button is gone
  }

  async function onRetry(doc: DocumentResponse) {
    setRetrying((s) => new Set(s).add(doc.document_id));
    setStatus(`Retrying ${doc.title}…`);
    try {
      await retry(doc.document_id);
      setStatus(`Retrying ${doc.title}. Processing again.`);
    } catch (error) {
      // A 401 is handled by the API client. A 409 means the attempts are used up; the refreshed row drops Retry.
      setStatus(error instanceof RetriesUsedUpError ? `${doc.title} could not be processed.` : `Couldn't retry ${doc.title}. Try again.`);
    }
    await refresh();
    setRetrying((s) => {
      const next = new Set(s);
      next.delete(doc.document_id);
      return next;
    });
  }

  // Switching tabs keeps the subject and date filters; the Archived tab has no State filter.
  function changeView(next: View) {
    if (next === view) return; // a click on the selected tab keeps its filters
    setView(next);
    setFilters(({ state: _state, ...rest }) => rest);
    void counts.refresh();
  }

  const markBusy = (documentId: string, on: boolean) =>
    setBusy((ids) => {
      const next = new Set(ids);
      if (on) next.add(documentId);
      else next.delete(documentId);
      return next;
    });

  async function changeArchived(doc: DocumentResponse, archiving: boolean) {
    markBusy(doc.document_id, true);
    try {
      await (archiving ? archive : restore)(doc.document_id);
      setStatus(archiving ? `${doc.title} archived. Find it under Archived.` : `${doc.title} restored.`);
      statusRegion.current?.focus(); // the row leaves this list, and its buttons with it
    } catch (error) {
      // A 401 is left to the session screen.
      if (!(error instanceof SessionExpiredError)) setStatus(`Couldn't ${archiving ? "archive" : "restore"} ${doc.title}. Try again.`);
    }
    await Promise.all([refresh(), counts.refresh(), refreshSubjects()]);
    markBusy(doc.document_id, false);
    if (document.activeElement === document.body) statusRegion.current?.focus(); // the disabled button lost focus
  }

  function openDelete(doc: DocumentResponse) {
    deleteDialog.current++;
    setDeleteBusy(false);
    setDeleteError(undefined);
    setDeleting(doc);
  }

  function cancelDelete() {
    deleteDialog.current++; // a request still in flight no longer belongs to a dialog
    setDeleting(null);
  }

  async function confirmDelete(doc: DocumentResponse) {
    const dialog = deleteDialog.current;
    const open = () => deleteDialog.current === dialog;
    setDeleteBusy(true);
    setDeleteError(undefined);
    let outcome: "deleted" | "processing" | "failed" = "deleted";
    let reason = "";
    try {
      await remove(doc.document_id);
    } catch (error) {
      if (error instanceof SessionExpiredError) {
        // The session screen replaces this page.
        if (open()) setDeleteBusy(false);
        return;
      }
      if (error instanceof DocumentProcessingError) {
        outcome = "processing";
        reason = error.message.replace(/\.$/, "");
      } else if (!(error instanceof DocumentGoneError)) outcome = "failed"; // already deleted elsewhere reads as done
    }
    if (open()) setDeleteBusy(false);
    if (outcome === "failed") {
      // The dialog is modal, so the error goes inside it.
      if (open()) setDeleteError(`Couldn't delete ${doc.title}. Try again.`);
      return;
    }
    if (open()) {
      setDeleting(null);
      if (outcome === "deleted") setDeleted(true);
    }
    setStatus(outcome === "deleted" ? `${doc.title} deleted.` : `Couldn't delete ${doc.title}${reason ? `: ${reason}` : ""}.`);
    await Promise.all([refresh(), counts.refresh(), refreshSubjects()]);
  }

  function archiveInstead(doc: DocumentResponse) {
    cancelDelete();
    void changeArchived(doc, true);
  }

  // An archived duplicate found by the server: restoring it turns the tray row into "Already in your library" with its link.
  async function restoreFromTray(item: TrayItem) {
    if (!item.documentId) return;
    try {
      await restore(item.documentId);
      updateTray(item.id, { archived: false });
      setStatus(`${item.name} restored.`);
    } catch (error) {
      if (!(error instanceof SessionExpiredError)) setStatus(`Couldn't restore ${item.name}. Try again.`);
    }
    if (document.activeElement === document.body) statusRegion.current?.focus(); // the Restore button is gone
    await Promise.all([refresh(), counts.refresh(), refreshSubjects()]);
  }

  const pick = () => input.current?.click();

  return (
    <>
      <PageHeader
        title="Library"
        headingRef={headingRef}
        count={counts.active ? `${counts.active} active ${counts.active === 1 ? "document" : "documents"}` : undefined}
        description="Your documents. They're private to you, and the tutor answers only from them."
        actions={
          documents !== null && !firstRun ? (
            <>
              <p className={styles.rights}>Only upload documents you have the right to use.</p>
              <Button variant="primary" icon={Upload} onClick={pick}>Upload</Button>
            </>
          ) : undefined
        }
      />
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        aria-label="Upload PDFs"
        onChange={onPick}
      />
      <p ref={statusRegion} tabIndex={-1} role="status" aria-live="polite" className={styles.status}>
        {status}
      </p>
      {failed.map((name, i) => (
        <p key={`${name}-${i}`} className={styles.error}>
          Couldn't upload {name}. Try again.
        </p>
      ))}
      {rejected.length > 0 && (
        <ul className={styles.rejected} aria-label="Files not uploaded">
          {rejected.map((r, i) => (
            <li key={`${r.name}-${i}`}>
              <AlertCircle aria-hidden="true" strokeWidth={1.75} />
              <span>
                <span className={styles.rejectedName}>{r.name}</span>
                <span className={styles.rejectedReason}>{r.reason}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
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
      {unavailable && documents === null && (
        <p className={styles.error}>
          Can't load your library. Retrying…
        </p>
      )}
      {showToolbar && (
        <div className={styles.toolbar}>
          <Tabs
            label="Library view"
            tabs={[
              { value: "active", label: "Active", count: counts.active ?? undefined },
              { value: "archived", label: "Archived", count: counts.archived ?? undefined },
            ]}
            value={view}
            onChange={changeView}
          />
          <LibraryFilters ref={subjectSelect} filters={filters} onChange={setFilters} subjects={subjects} count={list ? list.length : null} needsSubjects={list ? list.filter((d) => d.state === "awaiting_subjects").length : 0} onClear={clearFilters} showState={!archivedView} />
        </div>
      )}
      {showToolbar && archivedView && (
        <p className={styles.notice}>
          <Info aria-hidden="true" strokeWidth={1.5} />
          {ARCHIVED_NOTICE}
        </p>
      )}
      {list?.length === 0 && filtered && (
        <EmptyState icon={Filter} title="No documents match these filters" actions={<Button onClick={clearFilters}>Clear filters</Button>}>
          <p>Try another subject{archivedView ? "" : ", state"} or a wider date range.</p>
        </EmptyState>
      )}
      {archivedView && list?.length === 0 && !filtered && (
        <EmptyState icon={Archive} title="No archived documents">
          <p>Archived documents leave search until you restore them.</p>
        </EmptyState>
      )}
      {allArchived && (
        <EmptyState
          icon={Archive}
          title="No active documents"
          actions={
            <Button variant="primary" icon={Upload} onClick={pick}>
              Upload
            </Button>
          }
        >
          <p>Your documents are all archived. Restore one from Archived, or upload a new one.</p>
        </EmptyState>
      )}
      {firstRun && (
        <EmptyState
          variant="dropzone"
          icon={Upload}
          title="Upload your first document"
          note="Or drop files anywhere on this page. You can add several at once."
          actions={
            <Button variant="primary" size="lg" icon={Upload} onClick={pick}>
              Choose PDFs
            </Button>
          }
        >
          {limits ? (
            <p>
              PDFs up to {megabytes(limits.max_bytes)} MB and {limits.max_pages} pages. Your documents stay private to you.
            </p>
          ) : (
            <p>Your documents stay private to you.</p>
          )}
          <p>Only upload documents you have the right to use.</p>
        </EmptyState>
      )}
      {list && list.length > 0 && (
        <DocumentTable
          documents={list}
          onRetry={(d) => void onRetry(d)}
          retrying={retrying}
          onChooseSubjects={setPicking}
          uploading={uploading}
          onArchive={(d) => void changeArchived(d, true)}
          onRestore={(d) => void changeArchived(d, false)}
          onOpen={(d, o) => setDetails({ id: d.document_id, editing: Boolean(o?.editTitle) })}
          onDelete={openDelete}
          busy={busy}
        />
      )}
      {picking && <SubjectPicker document={picking} load={loadSuggestions} save={saveSubjects} onClose={closePicker} onSaved={(doc) => void onSaved(doc, picking.state === "ready")} />}
      {details && (
        <DocumentDetailsPanel
          key={details.id}
          documentId={details.id}
          startEditing={details.editing}
          load={loadDetails}
          saveTitle={saveTitle}
          archive={archive}
          restore={restore}
          onChanged={() => void Promise.all([refresh(), counts.refresh(), refreshSubjects()])}
          onChangeSubjects={changeFromDetails}
          onClose={() => setDetails(null)}
        />
      )}
      {deleting && <DeleteDialog doc={deleting} busy={deleteBusy} error={deleteError} onCancel={cancelDelete} onDelete={() => void confirmDelete(deleting)} onArchive={() => archiveInstead(deleting)} />}
      {dragging && !picking && !details && <DropOverlay />}
      <UploadTray items={tray} onClose={closeTray} onRestore={(item) => void restoreFromTray(item)} />
    </>
  );
}
