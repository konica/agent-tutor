import { AlertCircle, Info, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import { SessionExpiredError } from "../../auth/authClient";
import { findInLibrary, loadDocuments, loadSubjectSuggestions, loadUploadLimits, megabytes, rejectionReason, saveSubjects as saveChosenSubjects, uploadPdf, type DocumentResponse, type SubjectSuggestions, type UploadLimits } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { DocumentTable } from "./DocumentTable";
import { SubjectPicker } from "./SubjectPicker";
import styles from "./LibraryPage.module.css";
import { useDocuments } from "./useDocuments";

type Props = {
  load?: () => Promise<DocumentResponse[]>;
  upload?: (file: File) => Promise<void>;
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

const defaultUpload = (file: File) => uploadPdf(file);
const defaultLoadLimits = () => loadUploadLimits();
const defaultCheck = (file: File) => findInLibrary(file);

const defaultLoadSuggestions = (id: string) => loadSubjectSuggestions(id);
const defaultSaveSubjects = (id: string, choice: { subject_ids: string[]; new_names: string[] }) => saveChosenSubjects(id, choice);

// Library with a plain file picker (US-2 first slice). Drop zone, upload tray, tabs and filters come later.
export function LibraryPage({ load = loadDocuments, upload = defaultUpload, loadLimits = defaultLoadLimits, check = defaultCheck, loadSuggestions = defaultLoadSuggestions, saveSubjects = defaultSaveSubjects, pollMs = 2000 }: Props) {
  const { documents, unavailable, refresh } = useDocuments(load, pollMs);
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState<string | null>(null);
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const [alreadyIn, setAlreadyIn] = useState<{ name: string; documentId: string }[]>([]);
  const seen = useRef<Map<string, DocumentResponse["state"]> | null>(null);
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
    seen.current?.set(doc.document_id, "ready"); // the poll must not announce "is ready." again
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
      .filter((d) => before.has(d.document_id) && before.get(d.document_id) !== d.state)
      .map(announceChange)
      .filter((message): message is string => message !== null);
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

  async function onPick(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = ""; // picking the same file again fires change again
    setFailed(null);
    setRejected([]);
    setAlreadyIn([]);
    const current = limits ?? (await ensureLimits());
    // One combined message for the whole pick, so no file's result overwrites another's in the live region.
    const parts: string[] = [];
    for (const file of files) {
      const reason = rejectionReason(file, current);
      if (reason) {
        setRejected((list) => [...list, { name: file.name, reason }]);
        parts.push(`${file.name}: ${reason}`);
        setStatus(parts.join(" "));
        continue;
      }
      setStatus([...parts, `Checking ${file.name}…`].join(" "));
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
        parts.push(`${file.name}: Already in your library.`);
        setStatus(parts.join(" "));
        continue;
      }
      setFailed(null);
      setStatus([...parts, `Uploading ${file.name}…`].join(" "));
      try {
        if (!current) throw new Error("Upload limits unavailable");
        await upload(file);
        parts.push(`Uploaded ${file.name}. Processing.`);
      } catch {
        // A 401 is handled by the API client: the session screen replaces this page.
        parts.push(`Upload failed: ${file.name}.`);
        setFailed(file.name);
      }
      setStatus(parts.join(" "));
      await refresh();
    }
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
        onChange={(e) => void onPick(e)}
      />
      <p ref={statusRegion} tabIndex={-1} role="status" aria-live="polite" className={styles.status}>
        {status}
      </p>
      {failed && (
        <p className={styles.error}>
          Couldn't upload {failed}. Try again.
        </p>
      )}
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
          note="You can pick several PDFs at once."
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
      {documents && documents.length > 0 && <DocumentTable documents={documents} onChooseSubjects={setPicking} />}
      {picking && <SubjectPicker document={picking} load={loadSuggestions} save={saveSubjects} onClose={() => setPicking(null)} onSaved={(doc) => void onSaved(doc)} />}
    </>
  );
}
