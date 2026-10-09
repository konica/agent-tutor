import { Archive, CircleAlert, FileText, Info, Pencil, RefreshCw, RotateCcw, Tag, Trash2 } from "lucide-react";

import type { DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { RowMenu } from "../../components/RowMenu/RowMenu";
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
  if (doc.archived) return <StateBadge state="archived" />; // archived is a flag on any state (PRD §9.5); the row shows only that
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
  onArchive?: (doc: DocumentResponse) => void;
  onRestore?: (doc: DocumentResponse) => void;
  onOpen?: (doc: DocumentResponse, options?: { editTitle?: boolean }) => void;
  onDelete?: (doc: DocumentResponse) => void;
  busy?: ReadonlySet<string>; // document ids whose archive or restore is running
};

// An archived row offers Restore and Delete…: its subjects can't change until restored (PRD US-10), and it isn't processed again.
// A ready row's More menu offers Change subjects (the picker opens with its subjects selected).
function Actions({ doc, onRetry, retrying, onChooseSubjects, uploading, onArchive, onRestore, onOpen, onDelete, busy }: Omit<Props, "documents" | "uploading" | "busy"> & { doc: DocumentResponse; uploading: boolean; busy: boolean }) {
  const canDelete = onDelete && doc.state !== "processing"; // the worker is still writing a processing document's content, archived or not
  const label = `More actions for ${doc.title}`;
  const deleteItem = { label: "Delete…", icon: Trash2, danger: true, onSelect: () => onDelete?.(doc) };
  if (doc.archived)
    return (
      <>
        {onRestore && (
          <Button size="sm" icon={RotateCcw} aria-label={`Restore ${doc.title}`} disabled={busy} onClick={() => onRestore(doc)}>
            Restore
          </Button>
        )}
        {canDelete && <RowMenu label={label} disabled={busy} items={[deleteItem]} />}
      </>
    );
  const changeSubjects = doc.state === "ready" && onChooseSubjects ? [{ label: "Change subjects", icon: Tag, onSelect: () => onChooseSubjects(doc) }] : [];
  const items = [
    ...(onOpen ? [{ label: "Details", icon: Info, onSelect: () => onOpen(doc) }] : []),
    ...changeSubjects,
    ...(onOpen && doc.state !== "failed" ? [{ label: "Edit title", icon: Pencil, onSelect: () => onOpen(doc, { editTitle: true }) }] : []),
    { label: "Archive", icon: Archive, onSelect: () => onArchive?.(doc) },
    ...(canDelete ? [deleteItem] : []),
  ];
  return (
    <>
      {doc.state === "awaiting_subjects" && onChooseSubjects && (
        <Button size="sm" variant="primary" aria-label={`Choose subjects for ${doc.title}`} disabled={busy} onClick={() => onChooseSubjects(doc)}>
          Choose subjects
        </Button>
      )}
      {doc.state === "failed" && doc.can_retry && (
        <Button size="sm" icon={RefreshCw} aria-label={`Retry ${doc.title}`} disabled={busy || retrying.has(doc.document_id)} onClick={() => onRetry(doc)}>
          Retry
        </Button>
      )}
      {onArchive && !uploading && <RowMenu label={label} disabled={busy} items={items} />}
    </>
  );
}

export function DocumentTable({ documents, onRetry, retrying, onChooseSubjects, uploading = NONE, onArchive, onRestore, onOpen, onDelete, busy = NONE }: Props) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col">Document</th>
          <th scope="col" className={styles.colSubjects}>Subjects</th>
          <th scope="col" className={styles.colState}>State</th>
          <th scope="col" className={styles.colUploaded}>Uploaded</th>
          <th scope="col" className={styles.colActions}>
            <span className="visually-hidden">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => {
          const by = byline(doc.authors, doc.year);
          const failed = !doc.archived && doc.state === "failed" && Boolean(doc.failure_reason);
          return (
            <tr key={doc.document_id} id={`document-${doc.document_id}`} className={doc.archived ? styles.archived : doc.state === "awaiting_subjects" ? styles.needs : undefined}>
              <td>
                <span className={styles.doc}>
                  <FileText className={styles.fileIcon} strokeWidth={1.5} aria-hidden="true" />
                  {onOpen && !uploading.has(doc.document_id) ? (
                    <button type="button" className={`${styles.title} ${styles.titleButton}`} title={doc.title} onClick={() => onOpen(doc)}>
                      {doc.title}
                    </button>
                  ) : (
                    <span className={styles.title} title={doc.title}>
                      {doc.title}
                    </span>
                  )}
                  {by && <span className={styles.byline} title={by}>{by}</span>}
                </span>
              </td>
              <td className={doc.subjects.length ? undefined : styles.muted}>
                <div className={styles.subjects} title={doc.subjects.map((s) => s.name).join(", ") || undefined}>{doc.subjects.length ? doc.subjects.map((s) => <SubjectChip key={s.subject_id} name={s.name} hueKey={s.subject_id} truncate />) : "Not chosen yet"}</div>
              </td>
              <td>
                <div className={failed ? `${styles.state} ${styles.stateFailed}` : styles.state}>
                  <StateCell doc={doc} uploading={uploading.has(doc.document_id)} />
                </div>
              </td>
              <td className={styles.date}>{uploadedOn(doc.created_at)}</td>
              <td className={styles.actions}>
                <div className={styles.actionsRow}>
                  <Actions doc={doc} onRetry={onRetry} retrying={retrying} onChooseSubjects={onChooseSubjects} uploading={uploading.has(doc.document_id)} onArchive={onArchive} onRestore={onRestore} onOpen={onOpen} onDelete={onDelete} busy={busy.has(doc.document_id)} />
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
