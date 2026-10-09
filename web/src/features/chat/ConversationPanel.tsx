import { Archive, FileText, Info, NotebookPen, Plus, X } from "lucide-react";
import { useEffect, useRef } from "react";

import type { ThreadDocumentResponse } from "../../api/generated/types.gen";
import { Button } from "../../components/Button/Button";
import { IconButton } from "../../components/Button/IconButton";
import styles from "./ConversationPanel.module.css";

type Props = {
  id: string;
  documents: ThreadDocumentResponse[];
  /** The documents used couldn't be loaded after an answer: the empty list then means "unknown", not "none". */
  documentsFailed?: boolean;
  /** The conversation's thread, once the server has started one; null before the first question. */
  threadId: string | null;
  /** The first answer is done: the conversation exists and has something to summarize. */
  answered: boolean;
  showCitations: boolean;
  onShowCitationsChange: (on: boolean) => void;
  /** Opens the Add documents picker; the button shows once the conversation exists. */
  onAddDocuments?: () => void;
  /** Takes a document off the list; the parent drops its row, and focus moves to the next row's remove button. */
  onRemoveDocument?: (documentId: string) => void;
};

// Where focus goes once a removed row is gone: a row's remove button, or Add documents.
type FocusTarget = { removed: string; next: string | "add" };

// The row's tooltip: the full title (it may be truncated), then authors · year when known.
function tooltip(d: ThreadDocumentResponse): string {
  const byline = [d.authors.join(", "), d.year === null ? "" : String(d.year)].filter(Boolean).join(" · ");
  return byline ? `${d.title}\n${byline}` : d.title;
}

/**
 * The chat's left pane (DESIGN.md → Chat, PRD Q60): the conversation's documents, its Lesson Note, and actions.
 * Each row has a remove button (US-4c); Add documents opens the picker once the conversation exists. A document the learner
 * added that no answer has used yet is marked "Added". Rows open nothing yet (#123); Summarize lesson (US-7) and Archive
 * conversation (US-13) stay disabled until their stories.
 */
export function ConversationPanel({
  id,
  documents,
  documentsFailed = false,
  threadId,
  answered,
  showCitations,
  onShowCitationsChange,
  onAddDocuments,
  onRemoveDocument,
}: Props) {
  const panel = useRef<HTMLElement>(null);
  const focusAfterRemove = useRef<FocusTarget | null>(null);

  // Runs after the parent dropped the removed row; until then focus stays on its button.
  useEffect(() => {
    const target = focusAfterRemove.current;
    if (!target || documents.some((d) => d.document_id === target.removed)) return;
    focusAfterRemove.current = null;
    const root = panel.current;
    const row = target.next === "add" ? null : root?.querySelector<HTMLElement>(`[data-remove="${CSS.escape(target.next)}"]`);
    (row ?? root?.querySelector<HTMLElement>("[data-add-documents]"))?.focus();
  }, [documents]);

  function remove(documentId: string) {
    const at = documents.findIndex((d) => d.document_id === documentId);
    const next = documents[at + 1] ?? documents[at - 1];
    focusAfterRemove.current = { removed: documentId, next: next ? next.document_id : "add" };
    onRemoveDocument?.(documentId);
  }

  return (
    <aside ref={panel} id={id} className={styles.panel} aria-label="Conversation">
      <section className={styles.section} aria-labelledby={`${id}-documents`}>
        <h2 id={`${id}-documents`} className={styles.heading}>
          Documents {!documentsFailed && <span className={styles.count}>{documents.length}</span>}
        </h2>
        {documentsFailed ? (
          <p className={styles.text}>Couldn't load the documents used.</p>
        ) : documents.length === 0 ? (
          <p className={styles.text}>Documents used to answer will appear here.</p>
        ) : (
          <ul className={styles.list}>
            {documents.map((d) => (
              <li key={d.document_id} className={styles.row} title={tooltip(d)}>
                <FileText className={styles.rowIcon} strokeWidth={1.5} aria-hidden="true" />
                <span className={`${styles.title} ${d.deleted ? styles.gone : ""}`}>{d.title}</span>
                {d.deleted ? (
                  <span className={styles.badge}>
                    <X className={styles.badgeIcon} strokeWidth={1.5} aria-hidden="true" />
                    Deleted
                  </span>
                ) : d.archived ? (
                  <span className={styles.badge}>Archived</span>
                ) : (
                  d.added_by === "learner" && !d.used && <span className={`${styles.badge} ${styles.added}`}>Added</span>
                )}
                {onRemoveDocument && (
                  <IconButton
                    label={`Remove ${d.title} from this conversation`}
                    data-tip="Remove from this conversation"
                    icon={X}
                    className={styles.remove}
                    data-remove={d.document_id}
                    onClick={() => remove(d.document_id)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
        {!documentsFailed && documents.some((d) => d.deleted) && (
          <p className={styles.note}>
            <Info className={styles.noteIcon} strokeWidth={1.5} aria-hidden="true" />
            Deleted documents can't be opened.
          </p>
        )}
        {onAddDocuments && threadId !== null && (
          <Button
            variant="quiet"
            size="sm"
            icon={Plus}
            className={styles.action}
            aria-haspopup="dialog"
            data-add-documents
            onClick={onAddDocuments}
          >
            Add documents
          </Button>
        )}
      </section>

      <section className={styles.section} aria-labelledby={`${id}-note`}>
        <h2 id={`${id}-note`} className={styles.heading}>
          Lesson Note
        </h2>
        {answered ? (
          <>
            <p className={styles.text}>Turn this conversation into a note you can edit.</p>
            <Button size="sm" icon={NotebookPen} className={styles.action} disabled>
              Summarize lesson
            </Button>
          </>
        ) : (
          <p className={styles.text}>After the first answer you can summarize this conversation into a note.</p>
        )}
      </section>

      <section className={styles.section} aria-labelledby={`${id}-actions`}>
        <h2 id={`${id}-actions`} className={styles.heading}>
          Actions
        </h2>
        <button
          type="button"
          role="switch"
          aria-checked={showCitations}
          className={styles.switch}
          onClick={() => onShowCitationsChange(!showCitations)}
        >
          <span className={styles.track} aria-hidden="true">
            <span className={styles.thumb} />
          </span>
          Show citations
        </button>
        {threadId !== null && (
          <Button variant="quiet" size="sm" icon={Archive} className={styles.action} disabled>
            Archive conversation
          </Button>
        )}
      </section>
    </aside>
  );
}
