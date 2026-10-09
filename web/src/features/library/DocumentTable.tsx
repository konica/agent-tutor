import { CircleAlert, FileText, RefreshCw } from "lucide-react";

import type { DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { StateBadge } from "../../components/StateBadge/StateBadge";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import { APP_TIME_ZONE } from "../../time";
import { byline } from "./byline";
import styles from "./DocumentTable.module.css";

// Calendar day in the app time zone (PRD D27), so the shown day matches the filter days.
const dayKey = (date: Date) => date.toLocaleDateString("en-CA", { timeZone: APP_TIME_ZONE });

// Short form: the year appears only when it is not the current one.
function uploadedOn(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (dayKey(date) === dayKey(now)) return "Today";
  const sameYear = dayKey(date).slice(0, 4) === dayKey(now).slice(0, 4);
  return date.toLocaleDateString(undefined, { timeZone: APP_TIME_ZONE, day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

const NONE: ReadonlySet<string> = new Set();

function StateCell({ doc, uploading }: { doc: DocumentResponse; uploading: boolean }) {
  // The API creates the row when it presigns the upload; until the browser has sent the file it reads "Uploading".
  if (uploading) return <StateBadge state="uploading" />;
  const retried = doc.state === "processing" && doc.attempt && doc.attempt > 1 ? `Attempt ${doc.attempt} of ${doc.max_attempts}` : null;
  const hint = doc.state === "processing" ? [retried, "You can choose subjects when processing finishes."].filter(Boolean).join(" · ") : null;
  return (
    <>
      <StateBadge state={doc.state} />
      {hint && (
        <span className={styles.hint} title={hint}>
          {hint}
        </span>
      )}
      {doc.state === "failed" && doc.failure_reason && (
        <span className={styles.reason}>
          <CircleAlert className={styles.reasonIcon} strokeWidth={1.5} aria-hidden="true" />
          {doc.failure_reason}
        </span>
      )}
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
      <colgroup>
        <col />
        <col className={styles.colSubjects} />
        <col className={styles.colState} />
        <col className={styles.colUploaded} />
        <col className={styles.colActions} />
      </colgroup>
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
          const failed = doc.state === "failed" && Boolean(doc.failure_reason);
          return (
            <tr key={doc.document_id} id={`document-${doc.document_id}`} className={doc.state === "awaiting_subjects" ? styles.needs : undefined}>
              <td>
                <span className={styles.doc}>
                  <FileText className={styles.fileIcon} strokeWidth={1.5} aria-hidden="true" />
                  <span className={styles.title} title={doc.title}>
                    {doc.title}
                  </span>
                  {by && <span className={styles.byline}>{by}</span>}
                </span>
              </td>
              <td className={doc.subjects.length ? undefined : styles.muted}>
                <div className={styles.subjects}>{doc.subjects.length ? doc.subjects.map((s) => <SubjectChip key={s.subject_id} name={s.name} hueKey={s.subject_id} />) : "Not chosen yet"}</div>
              </td>
              <td>
                <div className={failed ? `${styles.state} ${styles.stateFailed}` : styles.state}>
                  <StateCell doc={doc} uploading={uploading.has(doc.document_id)} />
                </div>
              </td>
              <td className={styles.date}>{uploadedOn(doc.created_at)}</td>
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
