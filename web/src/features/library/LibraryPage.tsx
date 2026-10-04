import { Upload } from "lucide-react";
import { useRef, useState, type ChangeEvent } from "react";

import { loadDocuments, uploadPdf, type DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { DocumentTable } from "./DocumentTable";
import styles from "./LibraryPage.module.css";
import { useDocuments } from "./useDocuments";

type Props = {
  load?: () => Promise<DocumentResponse[]>;
  upload?: (file: File) => Promise<void>;
  pollMs?: number;
};

const defaultUpload = (file: File) => uploadPdf(file);

// Library with a plain file picker (US-2 first slice). Drop zone, upload tray, tabs and filters come later.
export function LibraryPage({ load = loadDocuments, upload = defaultUpload, pollMs = 2000 }: Props) {
  const { documents, unavailable, refresh } = useDocuments(load, pollMs);
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState<string | null>(null);

  async function onPick(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = ""; // picking the same file again fires change again
    for (const file of files) {
      setFailed(null);
      setStatus(`Uploading ${file.name}…`);
      try {
        await upload(file);
        setStatus(`Uploaded ${file.name}. Processing.`);
      } catch {
        setStatus("");
        setFailed(file.name);
      }
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
      <p role="status" aria-live="polite" className={styles.status}>
        {status}
      </p>
      {failed && (
        <p role="alert" className={styles.error}>
          Couldn't upload {failed}. Try again.
        </p>
      )}
      {unavailable && documents === null && (
        <p role="alert" className={styles.error}>
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
          <p>PDFs up to 50 MB and 500 pages. Your documents stay private to you.</p>
        </EmptyState>
      )}
      {documents && documents.length > 0 && <DocumentTable documents={documents} />}
    </>
  );
}
