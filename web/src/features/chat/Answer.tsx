import { FileText } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { formatCitation, type ChatCitation } from "../../api/chat";
import { Button } from "../../components/Button/Button";
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
  /** Helpful / Not helpful, at the end of the Sources line; the page places it itself when there is no line. */
  rating?: ReactNode;
};

// The Sources line shows this many chips until the learner asks for the rest.
const COLLAPSED = 3;

// A turn's answer and its Sources line (DESIGN.md → Chat). A declined turn has neither.
export function Answer({ text, citations, showCitations, deletedIds, shownChunkId, onOpenCitation, rating }: Props) {
  const listId = useId();
  const moreId = useId();
  // Expanded only for the citations it was expanded for: another conversation's turn at this index brings new ones, so
  // it starts collapsed, as a new answer and a reload do.
  const [expandedFor, setExpandedFor] = useState<ChatCitation[] | null>(null);
  const expanded = expandedFor === citations;
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
        onClick={(event) => {
          // A hidden source's chip shows, so the learner sees which one is open.
          if (citations.indexOf(c) >= COLLAPSED) setExpandedFor(citations);
          onOpenCitation(c, event.currentTarget);
        }}
      >
        {p.text}
      </button>
    );
  }

  function chip(c: ChatCitation) {
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
          {/* Each source shows the [n] the answer's text uses for it; an answer may cite [2] without [1]. The first three,
              in the order the answer first cites them, show; the rest come after the button, so they follow it in tab
              order once shown. */}
          <div className={styles.sourceChips}>
            <ul className={styles.sourceList} aria-labelledby={listId}>
              {citations.slice(0, COLLAPSED).map(chip)}
            </ul>
            {citations.length > COLLAPSED && (
              <>
                {/* The same button either way, so focus stays on it. */}
                <Button
                  variant="quiet"
                  size="sm"
                  className={styles.more}
                  aria-expanded={expanded}
                  aria-controls={moreId}
                  onClick={() => setExpandedFor(expanded ? null : citations)}
                >
                  {expanded ? "Show less" : `Show ${citations.length - COLLAPSED} more`}
                </Button>
                <ul id={moreId} className={styles.sourceList} aria-label="More sources" hidden={!expanded}>
                  {citations.slice(COLLAPSED).map(chip)}
                </ul>
              </>
            )}
          </div>
          {rating}
        </div>
      )}
    </>
  );
}
