import { FileText } from "lucide-react";
import { useId } from "react";

import { formatCitation, type ChatCitation } from "../../api/chat";
import styles from "./Answer.module.css";
import { splitMarkers, type Piece } from "./citationMarkers";

type Props = {
  /** The answer as the model wrote it: always rendered as text. */
  text: string;
  citations: ChatCitation[];
  /** The panel's Show citations switch. */
  showCitations: boolean;
  /** Documents the conversation's list marks deleted. */
  deletedIds: ReadonlySet<string>;
  /** This turn's chunk whose passage is open beside the conversation; null when none of its sources is. */
  shownChunkId: string | null;
  /** Opens the citation's document beside the conversation; focus goes back to `from` when it closes. */
  onOpenCitation: (citation: ChatCitation, from: HTMLElement) => void;
};

// A turn's answer and its Sources line (DESIGN.md → Chat). A declined turn has neither.
export function Answer({ text, citations, showCitations, deletedIds, shownChunkId, onOpenCitation }: Props) {
  const listId = useId();
  // Markers link once the answer's citations have arrived (they follow its last words) and while citations are shown.
  const linked = showCitations && citations.length > 0;
  const byNumber = new Map(citations.map((c) => [c.n, c]));

  // A marker number with a source in this answer opens it, as its Sources chip does; any other piece stays text.
  // The pieces render even while markers stay text, so toggling citations keeps the live answer's text nodes.
  function piece(p: Piece, index: number) {
    const c = !linked || p.n === undefined ? undefined : byNumber.get(p.n);
    if (!c) return p.text;
    if (c.deleted || deletedIds.has(c.document_id)) {
      return (
        <span key={index} title="Deleted document">
          {p.text}
        </span>
      );
    }
    const name = `Source ${c.n}: ${formatCitation(c)}${c.archived ? ", archived" : ""}`;
    return (
      <button
        key={index}
        type="button"
        className={styles.marker}
        title={name}
        aria-label={name}
        aria-current={shownChunkId === c.chunk_id ? "true" : undefined}
        data-chunk-id={c.chunk_id}
        onClick={(event) => onOpenCitation(c, event.currentTarget)}
      >
        {p.text}
      </button>
    );
  }

  return (
    <>
      {/* Text nodes only: the model's words are never read as HTML. */}
      {text && <p className={styles.answer}>{splitMarkers(text).map(piece)}</p>}
      {showCitations && citations.length > 0 && (
        <div className={styles.sources}>
          <span className={styles.sourcesLabel} id={listId}>
            Sources
          </span>
          {/* Each source shows the [n] the answer's text uses for it; an answer may cite [2] without [1]. */}
          <ul className={styles.sourceList} aria-labelledby={listId}>
            {citations.map((c) => {
              // A citation to a deleted document keeps its [n] but loses the title and page.
              if (c.deleted || deletedIds.has(c.document_id)) {
                return (
                  <li key={c.chunk_id}>
                    <span className={`${styles.source} ${styles.sourceDeleted}`} title="Deleted document">
                      <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
                      <span className={styles.sourceMarker}>[{c.n}]</span> Deleted document
                    </span>
                  </li>
                );
              }
              // The chip whose passage is open beside the conversation; a panel row's open clears it.
              const isShown = shownChunkId === c.chunk_id;
              const pageText = c.page === null ? "page unavailable" : `p. ${c.page}`;
              const state = isShown ? "Shown beside the conversation" : "Open beside the conversation";
              return (
                <li key={c.chunk_id}>
                  <button
                    type="button"
                    className={isShown ? `${styles.source} ${styles.sourceShown}` : styles.source}
                    title={formatCitation(c)}
                    aria-label={`${c.document_title}, ${pageText}${c.archived ? ", archived" : ""}. ${state}`}
                    aria-current={isShown ? "true" : undefined}
                    data-chunk-id={c.chunk_id}
                    onClick={(event) => onOpenCitation(c, event.currentTarget)}
                  >
                    <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
                    <span className={styles.sourceMarker}>[{c.n}]</span>{" "}
                    <span className={styles.sourceTitle}>{c.document_title}</span>{" "}
                    <span className={styles.sourcePage}>· {pageText}</span>
                    {/* An archived document's citation still opens it, marked as archived. */}
                    {c.archived && <span className={styles.sourceBadge}>Archived</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </>
  );
}
