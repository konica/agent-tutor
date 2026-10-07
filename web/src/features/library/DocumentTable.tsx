import { FileText, RefreshCw } from "lucide-react";

import type { DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { StateBadge } from "../../components/StateBadge/StateBadge";
import styles from "./DocumentTable.module.css";

function uploadedOn(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (date.toDateString() === now.toDateString()) return "Today";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function StateCell({ doc }: { doc: DocumentResponse }) {
  return (
    <>
      <StateBadge state={doc.state} />
      {doc.state === "processing" && doc.attempt && doc.attempt > 1 && (
        <p className={styles.hint}>
          Attempt {doc.attempt} of {doc.max_attempts}.
        </p>
      )}
      {doc.state === "processing" && <p className={styles.hint}>You can choose subjects when processing finishes.</p>}
      {doc.state === "failed" && doc.failure_reason && <p className={styles.reason}>{doc.failure_reason}</p>}
    </>
  );
}

type Props = {
  documents: DocumentResponse[];
  onRetry: (doc: DocumentResponse) => void;
  retrying: ReadonlySet<string>;
};

export function DocumentTable({ documents, onRetry, retrying }: Props) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col">Document</th>
          <th scope="col">Subjects</th>
          <th scope="col">State</th>
          <th scope="col">Uploaded</th>
          <th scope="col">
            <span className="visually-hidden">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => (
          <tr key={doc.document_id} id={`document-${doc.document_id}`}>
            <td>
              <span className={styles.doc}>
                <span className={styles.fileIcon}>
                  <FileText strokeWidth={1.5} aria-hidden="true" />
                </span>
                <span className={styles.title}>{doc.title}</span>
              </span>
            </td>
            <td className={doc.subjects.length ? undefined : styles.muted}>{doc.subjects.map((s) => s.name).join(", ") || "Not chosen yet"}</td>
            <td>
              <StateCell doc={doc} />
            </td>
            <td className={styles.muted}>{uploadedOn(doc.created_at)}</td>
            <td className={styles.actions}>
              {doc.state === "failed" && doc.can_retry && (
                <Button size="sm" icon={RefreshCw} aria-label={`Retry ${doc.title}`} disabled={retrying.has(doc.document_id)} onClick={() => onRetry(doc)}>
                  Retry
                </Button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
