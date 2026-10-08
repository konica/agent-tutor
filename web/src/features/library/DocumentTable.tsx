import { FileText, RefreshCw } from "lucide-react";

import type { DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { StateBadge } from "../../components/StateBadge/StateBadge";
import { APP_TIME_ZONE } from "../../time";
import { byline } from "./byline";
import styles from "./DocumentTable.module.css";

// Calendar day in the app time zone (PRD D27), so the shown day matches the filter days.
const dayKey = (date: Date) => date.toLocaleDateString("en-CA", { timeZone: APP_TIME_ZONE });

function uploadedOn(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (dayKey(date) === dayKey(now)) return "Today";
  return date.toLocaleDateString(undefined, { timeZone: APP_TIME_ZONE, day: "numeric", month: "short", year: "numeric" });
}

const NONE: ReadonlySet<string> = new Set();

function StateCell({ doc, uploading }: { doc: DocumentResponse; uploading: boolean }) {
  // The API creates the row when it presigns the upload; until the browser has sent the file it reads "Uploading".
  if (uploading) return <StateBadge state="uploading" />;
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
  onChooseSubjects?: (doc: DocumentResponse) => void;
  uploading?: ReadonlySet<string>; // document ids whose file is still being sent
};

export function DocumentTable({ documents, onRetry, retrying, onChooseSubjects, uploading = NONE }: Props) {
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
        {documents.map((doc) => {
          const by = byline(doc.authors, doc.year);
          return (
          <tr key={doc.document_id} id={`document-${doc.document_id}`}>
            <td>
              <span className={styles.doc}>
                <span className={styles.fileIcon}>
                  <FileText strokeWidth={1.5} aria-hidden="true" />
                </span>
                <span className={styles.titleStack}>
                  <span className={styles.title}>{doc.title}</span>
                  {by && <span className={styles.byline}>{by}</span>}
                </span>
              </span>
            </td>
            <td className={doc.subjects.length ? undefined : styles.muted}>{doc.subjects.map((s) => s.name).join(", ") || "Not chosen yet"}</td>
            <td>
              <StateCell doc={doc} uploading={uploading.has(doc.document_id)} />
            </td>
            <td className={styles.muted}>{uploadedOn(doc.created_at)}</td>
            <td className={styles.actions}>
              {doc.state === "awaiting_subjects" && onChooseSubjects && (
                <Button size="sm" variant="primary" aria-label={`Choose subjects for ${doc.title}`} onClick={() => onChooseSubjects(doc)}>
                  Choose subjects
                </Button>
              )}
              {doc.state === "failed" && doc.can_retry && (
                <Button size="sm" icon={RefreshCw} aria-label={`Retry ${doc.title}`} disabled={retrying.has(doc.document_id)} onClick={() => onRetry(doc)}>
                  Retry
                </Button>
              )}
            </td>
          </tr>
          );
        })}
      </tbody>
    </table>
  );
}
