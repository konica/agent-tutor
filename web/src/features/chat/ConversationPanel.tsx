import { Archive, FileText, Info, NotebookPen, X } from "lucide-react";

import type { ThreadDocumentResponse } from "../../api/generated/types.gen";
import { Button } from "../../components/Button/Button";
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
};

// The row's tooltip: the full title (it may be truncated), then authors · year when known.
function tooltip(d: ThreadDocumentResponse): string {
  const byline = [d.authors.join(", "), d.year === null ? "" : String(d.year)].filter(Boolean).join(" · ");
  return byline ? `${d.title}\n${byline}` : d.title;
}

/**
 * The chat's left pane (DESIGN.md → Chat, PRD Q60): the documents this conversation's answers used, its Lesson Note, and actions.
 * Rows open nothing yet (#123); Summarize lesson (US-7) and Archive conversation (US-13) stay disabled until their stories.
 */
export function ConversationPanel({
  id,
  documents,
  documentsFailed = false,
  threadId,
  answered,
  showCitations,
  onShowCitationsChange,
}: Props) {
  return (
    <aside id={id} className={styles.panel} aria-label="Conversation">
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
                {d.deleted && <span className="visually-hidden">Deleted: </span>}
                <FileText className={styles.rowIcon} strokeWidth={1.5} aria-hidden="true" />
                <span className={`${styles.title} ${d.deleted ? styles.gone : ""}`}>{d.title}</span>
                {d.deleted ? (
                  <span className={styles.badge}>
                    <X className={styles.badgeIcon} strokeWidth={1.5} aria-hidden="true" />
                    Deleted
                  </span>
                ) : (
                  d.archived && <span className={styles.badge}>Archived</span>
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
