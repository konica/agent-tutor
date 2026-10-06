import { AlertCircle, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import { loadDocuments, loadUploadLimits, megabytes, rejectionReason, retryProcessing, uploadPdf, type DocumentResponse, type UploadLimits } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { DocumentTable } from "./DocumentTable";
import styles from "./LibraryPage.module.css";
import { useDocuments } from "./useDocuments";

type Props = {
  load?: () => Promise<DocumentResponse[]>;
  upload?: (file: File) => Promise<void>;
  retry?: (documentId: string) => Promise<void>;
  loadLimits?: () => Promise<UploadLimits>;
  pollMs?: number;
};

function announceChange(doc: DocumentResponse): string | null {
  if (doc.state === "failed") return `${doc.title} failed${doc.failure_reason ? `: ${doc.failure_reason}` : ""}.`;
  if (doc.state === "awaiting_subjects") return `${doc.title} is ready to choose subjects.`;
  if (doc.state === "ready") return `${doc.title} is ready.`;
  return null;
}

const defaultUpload = (file: File) => uploadPdf(file);
const defaultRetry = (id: string) => retryProcessing(id);
const defaultLoadLimits = () => loadUploadLimits();

// Library with a plain file picker (US-2 first slice). Drop zone, upload tray, tabs and filters come later.
export function LibraryPage({ load = loadDocuments, upload = defaultUpload, retry = defaultRetry, loadLimits = defaultLoadLimits, pollMs = 2000 }: Props) {
  const { documents, unavailable, refresh } = useDocuments(load, pollMs);
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<ReadonlySet<string>>(new Set());
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const seen = useRef<Map<string, DocumentResponse["state"]> | null>(null);

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

  async function onRetry(doc: DocumentResponse) {
    setRetrying((s) => new Set(s).add(doc.document_id));
    setStatus(`Retrying ${doc.title}…`);
    try {
      await retry(doc.document_id);
      setStatus(`Retrying ${doc.title}. Processing again.`);
    } catch {
      // A 401 is handled by the API client; a 409 (attempts used up) shows on the refreshed row.
      setStatus(`Couldn't retry ${doc.title}. Try again.`);
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
        onChange={(e) => void onPick(e)}
      />
      <p role="status" aria-live="polite" className={styles.status}>
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
      {documents && documents.length > 0 && <DocumentTable documents={documents} onRetry={(d) => void onRetry(d)} retrying={retrying} />}
    </>
  );
}
