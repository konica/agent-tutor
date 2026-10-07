import { AlertCircle, Info, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import { SessionExpiredError } from "../../auth/authClient";
import { findInLibrary, loadDocuments, loadSubjectSuggestions, loadUploadLimits, megabytes, rejectionReason, RetriesUsedUpError, retryProcessing, saveSubjects as saveChosenSubjects, uploadPdf, type DocumentResponse, type SubjectSuggestions, type UploadEvents, type UploadLimits } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { UploadTray, type TrayItem } from "../../components/UploadTray/UploadTray";
import { DropOverlay } from "./DropOverlay";
import { DocumentTable } from "./DocumentTable";
import { SubjectPicker } from "./SubjectPicker";
import styles from "./LibraryPage.module.css";
import { useDocuments } from "./useDocuments";
import { usePageDrop } from "./usePageDrop";

type Props = {
  load?: () => Promise<DocumentResponse[]>;
  upload?: (file: File, events: UploadEvents) => Promise<void>;
  retry?: (documentId: string) => Promise<void>;
  loadLimits?: () => Promise<UploadLimits>;
  check?: (file: File) => Promise<string | null>;
  loadSuggestions?: (documentId: string) => Promise<SubjectSuggestions>;
  saveSubjects?: (documentId: string, choice: { subject_ids: string[]; new_names: string[] }) => Promise<DocumentResponse>;
  pollMs?: number;
};

function announceChange(doc: DocumentResponse): string | null {
  if (doc.state === "failed") return `${doc.title} failed${doc.failure_reason ? `: ${doc.failure_reason}` : ""}.`;
  if (doc.state === "awaiting_subjects") return `${doc.title} is ready to choose subjects.`;
  if (doc.state === "ready") return `${doc.title} is ready.`;
  return null;
}

const defaultUpload = (file: File, events: UploadEvents) => uploadPdf(file, events);
const defaultRetry = (id: string) => retryProcessing(id);
const defaultLoadLimits = () => loadUploadLimits();
const defaultCheck = (file: File) => findInLibrary(file);

const defaultLoadSuggestions = (id: string) => loadSubjectSuggestions(id);
const defaultSaveSubjects = (id: string, choice: { subject_ids: string[]; new_names: string[] }) => saveChosenSubjects(id, choice);

// Library: upload by picking or dropping PDFs (US-2), the upload tray, and the document list. Tabs and filters come later.
export function LibraryPage({ load = loadDocuments, upload = defaultUpload, retry = defaultRetry, loadLimits = defaultLoadLimits, check = defaultCheck, loadSuggestions = defaultLoadSuggestions, saveSubjects = defaultSaveSubjects, pollMs = 2000 }: Props) {
  const { documents, unavailable, refresh } = useDocuments(load, pollMs);
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState<string[]>([]);
  const [tray, setTray] = useState<TrayItem[]>([]);
  const [uploading, setUploading] = useState<ReadonlySet<string>>(new Set()); // document ids whose file is still being sent
  const traySeq = useRef(0);
  const [retrying, setRetrying] = useState<ReadonlySet<string>>(new Set());
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const [alreadyIn, setAlreadyIn] = useState<{ name: string; documentId: string }[]>([]);
  const seen = useRef<Map<string, DocumentResponse["state"]> | null>(null);
  const justSaved = useRef(new Set<string>()); // saved here, so the poll must not announce "is ready." over "Subjects saved."
  const [picking, setPicking] = useState<DocumentResponse | null>(null);
  const statusRegion = useRef<HTMLParagraphElement>(null);
  const wasPicking = useRef(false);

  // The dialog gives focus back to the row button; after a save that button is gone, so the status region takes it.
  useEffect(() => {
    if (picking) wasPicking.current = true;
    else if (wasPicking.current) {
      wasPicking.current = false;
      if (document.activeElement === document.body || document.activeElement === null) statusRegion.current?.focus();
    }
  }, [picking]);

  async function onSaved(doc: DocumentResponse) {
    justSaved.current.add(doc.document_id);
    seen.current?.set(doc.document_id, "ready");
    setStatus(`Subjects saved. ${doc.title} is ready to use.`);
    await refresh();
  }

  // One polite live region carries upload results and processing-state changes (DESIGN.md → Accessibility).
  useEffect(() => {
    if (!documents) return;
    const before = seen.current;
    seen.current = new Map(documents.map((d) => [d.document_id, d.state]));
    if (!before) return; // the first load is not a change
    const changes = documents
      .filter((d) => before.has(d.document_id) && before.get(d.document_id) !== d.state && !justSaved.current.has(d.document_id))
      .map(announceChange)
      .filter((message): message is string => message !== null);
    for (const d of documents) if (d.state === "ready") justSaved.current.delete(d.document_id);
    if (changes.length) setStatus(changes.join(" "));
  }, [documents]);

  const loadLimitsRef = useRef(loadLimits);
  const alive = useRef(true);
  useEffect(() => {
    loadLimitsRef.current = loadLimits; // an inline `loadLimits` must not restart the load
  }, [loadLimits]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

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

  const pick = () => input.current?.click();

  return (
    <>
      <PageHeader
        title="Library"
        description="Your documents. They're private to you, and the tutor answers only from them."
        actions={documents?.length ? <Button variant="primary" icon={Upload} onClick={pick}>Upload</Button> : undefined}
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
      {documents?.length === 0 && (
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
        </EmptyState>
      )}
      {documents && documents.length > 0 && <DocumentTable documents={documents} onRetry={(d) => void onRetry(d)} retrying={retrying} onChooseSubjects={setPicking} uploading={uploading} />}
      {picking && <SubjectPicker document={picking} load={loadSuggestions} save={saveSubjects} onClose={() => setPicking(null)} onSaved={(doc) => void onSaved(doc)} />}
      {dragging && <DropOverlay />}
      <UploadTray items={tray} onClose={closeTray} />
    </>
  );
}
