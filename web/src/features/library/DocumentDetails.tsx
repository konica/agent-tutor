import { Archive, CircleAlert, Pencil, RotateCcw } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import type { DocumentDetails } from "../../api/documents";
import { SessionExpiredError } from "../../auth/authClient";
import { Banner } from "../../components/Banner/Banner";
import { Button } from "../../components/Button/Button";
import { SidePanel } from "../../components/SidePanel/SidePanel";
import { StateBadge } from "../../components/StateBadge/StateBadge";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import { APP_TIME_ZONE } from "../../time";
import styles from "./DocumentDetails.module.css";

const MAX_TITLE = 300;

type Props = {
  documentId: string;
  startEditing?: boolean;
  load: (id: string) => Promise<DocumentDetails>;
  saveTitle: (id: string, title: string | null) => Promise<DocumentDetails>;
  archive: (id: string) => Promise<unknown>;
  restore: (id: string) => Promise<unknown>;
  onChanged: () => void; // the Library re-lists after a title, archive, or restore change
  onClose: () => void;
};

const dash = (value: string | number | null | undefined) => (value === null || value === undefined || value === "" ? "—" : String(value));

function emptyHint(details: DocumentDetails): string {
  if (details.state === "processing") return "You can choose subjects when processing finishes.";
  if (details.state === "awaiting_subjects") return "Processing has finished; choose its subjects from the Library.";
  return "No subjects yet.";
}

// The side panel behind a Library row (PRD US-10): facts, summary, subjects, the editable display title, and Archive or Restore.
export function DocumentDetailsPanel({ documentId, startEditing = false, load, saveTitle, archive, restore, onChanged, onClose }: Props) {
  const [details, setDetails] = useState<DocumentDetails | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [editing, setEditing] = useState(startEditing);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const headingId = useId();
  const labelId = useId();
  const inputId = useId();
  const helperId = useId();
  const errorId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const titleRowRef = useRef<HTMLDivElement>(null);
  const refocusEdit = useRef(false);

  useEffect(() => {
    let live = true;
    load(documentId).then(
      (loaded) => {
        if (!live) return;
        setDetails(loaded);
        setDraft(loaded.title);
      },
      () => live && setLoadError(true),
    );
    return () => {
      live = false;
    };
  }, [documentId, load]);

  const isEditing = editing && details !== null;
  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
    else if (refocusEdit.current) {
      refocusEdit.current = false;
      titleRowRef.current?.querySelector("button")?.focus(); // back to "Edit title"
    }
  }, [isEditing]);

  async function run(work: () => Promise<void>, message: string, failed: string) {
    setBusy(true);
    setError(null);
    try {
      await work();
      setStatus(message);
      onChanged();
    } catch (caught) {
      if (caught instanceof SessionExpiredError) return; // the session screen replaces this page
      setError((caught as Error).message || failed);
    } finally {
      setBusy(false);
    }
  }

  const startEdit = () => {
    setDraft(details?.title ?? "");
    setError(null);
    setEditing(true);
  };

  const cancelEdit = () => {
    refocusEdit.current = true;
    setError(null);
    setEditing(false);
  };

  const store = (title: string | null, message: string, failed: string) => {
    refocusEdit.current = true;
    void run(
      async () => {
        setDetails(await saveTitle(documentId, title));
        setEditing(false);
      },
      message,
      failed,
    );
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    const title = draft.replace(/\s+/g, " ").trim();
    if (!title) return setError("Enter a title");
    if (title.length > MAX_TITLE) return setError("Keep the title to 300 characters or fewer");
    store(title, "Title updated.", "Couldn't save the title. Try again.");
  }

  const resetTitle = () => store(null, "Title reset to the extracted title.", "Couldn't reset the title. Try again.");

  const changeArchive = (archiving: boolean) =>
    void run(
      async () => {
        await (archiving ? archive : restore)(documentId);
        setDetails(await load(documentId));
      },
      archiving ? "Document archived." : "Document restored.",
      archiving ? "Couldn't archive this document. Try again." : "Couldn't restore this document. Try again.",
    );

  function onTitleKeyDown(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation(); // cancels the edit; the panel stays open until the next Escape
    cancelEdit();
  }

  if (!details) {
    return (
      <SidePanel labelledBy={headingId} kicker="Document details" closeLabel="Close document details" onClose={onClose}>
        <p id={headingId} className={styles.muted}>
          {loadError ? "Couldn't load this document." : "Loading…"}
        </p>
      </SidePanel>
    );
  }

  const canRename = !details.archived && details.state !== "failed";
  const canReset = details.title_overridden && details.extracted_title !== null;
  const uploaded = new Date(details.created_at).toLocaleDateString(undefined, { timeZone: APP_TIME_ZONE, day: "numeric", month: "short", year: "numeric" });
  const facts: [string, string][] = [
    ["Authors", dash(details.authors.join(", "))],
    ["Year", dash(details.year)],
    ["DOI", dash(details.doi)],
    ["File name", dash(details.file_name)],
    ["Pages", dash(details.pages)],
    ["Uploaded", uploaded],
  ];
  const errorText = error && (
    <p id={errorId} role="alert" className={styles.error}>
      <CircleAlert className={styles.errorIcon} strokeWidth={1.5} aria-hidden="true" />
      {error}
    </p>
  );

  return (
    <SidePanel
      labelledBy={isEditing ? labelId : headingId}
      kicker="Document details"
      badge={<StateBadge state={details.archived ? "archived" : details.state} />}
      closeLabel="Close document details"
      onClose={onClose}
      footer={
        <div className={styles.footer}>
          {details.archived ? (
            <Button variant="primary" icon={RotateCcw} disabled={busy} onClick={() => changeArchive(false)}>
              Restore
            </Button>
          ) : (
            <Button icon={Archive} disabled={busy} onClick={() => changeArchive(true)}>
              Archive
            </Button>
          )}
        </div>
      }
    >
      <div className={styles.stack}>
        {details.state === "failed" && details.failure_reason && (
          <Banner variant="danger" title="Processing failed">
            {details.failure_reason}
          </Banner>
        )}
        {details.archived && (
          <Banner variant="info" title="Archived">
            Not used for answers. Citations to it in past conversations still open here. Restore it to change its subjects.
          </Banner>
        )}

        {isEditing ? (
          <form className={styles.form} onSubmit={submit}>
            <label id={labelId} htmlFor={inputId} className={styles.label}>
              Display title
            </label>
            <input
              id={inputId}
              ref={inputRef}
              data-autofocus
              className={[styles.input, error && styles.invalid].filter(Boolean).join(" ")}
              value={draft}
              aria-describedby={error ? `${helperId} ${errorId}` : helperId}
              aria-invalid={!!error}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onTitleKeyDown}
            />
            <p id={helperId} className={styles.helper}>
              Only changes how the title appears to you. Citations use this title.
            </p>
            {errorText}
            <div className={styles.actions}>
              <Button type="submit" variant="primary" size="sm" disabled={busy}>
                Save title
              </Button>
              <Button variant="quiet" size="sm" disabled={busy} onClick={cancelEdit}>
                Cancel
              </Button>
              {canReset && (
                <Button variant="ghost" size="sm" icon={RotateCcw} disabled={busy} onClick={resetTitle}>
                  Reset to extracted title
                </Button>
              )}
            </div>
          </form>
        ) : (
          <div className={styles.titleBlock}>
            <div className={styles.titleRow} ref={titleRowRef}>
              <h2 id={headingId} className={styles.title}>
                {details.title}
              </h2>
              {canRename && (
                <Button variant="ghost" size="sm" icon={Pencil} disabled={busy} onClick={startEdit}>
                  Edit title
                </Button>
              )}
            </div>
            {canReset && (
              <p className={styles.extracted}>
                Extracted title: {details.extracted_title} ·{" "}
                <Button variant="ghost" size="sm" icon={RotateCcw} disabled={busy} onClick={resetTitle}>
                  Reset to extracted title
                </Button>
              </p>
            )}
            {errorText}
          </div>
        )}

        <dl className={styles.facts}>
          {facts.map(([term, value]) => (
            <div key={term} className={styles.fact}>
              <dt>{term}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>

        <section className={styles.section}>
          <h3>Summary</h3>
          {details.summary ? <p className={styles.summary}>{details.summary}</p> : <p className={styles.muted}>A summary appears once Smart Tutor can read this PDF.</p>}
        </section>

        <section className={styles.section}>
          <h3>Subjects</h3>
          {details.subjects.length ? (
            <div className={styles.chips}>
              {details.subjects.map((subject) => (
                <SubjectChip key={subject.subject_id} name={subject.name} hueKey={subject.subject_id} />
              ))}
            </div>
          ) : (
            <p className={styles.muted}>{emptyHint(details)}</p>
          )}
        </section>
        <p role="status" aria-live="polite" className="visually-hidden">
          {status}
        </p>
      </div>
    </SidePanel>
  );
}
