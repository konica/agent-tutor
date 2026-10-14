import { FileText } from "lucide-react";
import { createContext, useContext, useId, useState, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatCitation, type ChatCitation } from "../../api/chat";
import { Button } from "../../components/Button/Button";
import styles from "./Answer.module.css";
import type { Piece } from "./citationMarkers";
import { remarkCitationMarkers } from "./remarkCitationMarkers";

type Props = {
  /** The answer as the model wrote it, rendered as Markdown. */
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

// Renders one marker piece; each Answer provides its own. Read through context so the Markdown components below keep
// one identity: new component functions on every render would remount the answer, and a marker that opened the viewer
// would lose the focus ChatPage gives back to it.
const MarkerContext = createContext<(p: Piece) => ReactNode>((p) => p.text);

function Marker({ n, children }: { n: number; children: ReactNode }) {
  return useContext(MarkerContext)({ text: String(children), n });
}

const remarkPlugins = [remarkGfm, remarkCitationMarkers];

// The model's headings sit under the page's h1 (title) and h2 (panel headings).
const components: Components = {
  h1: ({ node: _node, ...props }) => <h3 {...props} />,
  h2: ({ node: _node, ...props }) => <h4 {...props} />,
  h3: ({ node: _node, ...props }) => <h5 {...props} />,
  h4: ({ node: _node, ...props }) => <h6 {...props} />,
  h5: ({ node: _node, ...props }) => <h6 {...props} />,
  h6: ({ node: _node, ...props }) => <h6 {...props} />,
  // A wide table scrolls inside the answer, not the page.
  table: ({ node: _node, ...props }) => (
    <div className={styles.tableScroll}>
      <table {...props} />
    </div>
  ),
  // remarkCitationMarkers' spans; the answer's own HTML never reaches here (react-markdown shows it as text).
  span: ({ node, ...props }) => {
    const n = node?.properties?.dataMarker;
    return typeof n === "number" ? <Marker n={n}>{props.children}</Marker> : <span {...props} />;
  },
};

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

  // A marker number with a source in this answer opens it, as its Sources chip does; any other marker stays text.
  // Markers render even while they stay text, so toggling citations keeps the live answer's text nodes.
  function marker(p: Piece): ReactNode {
    const c = !linked || p.n === undefined ? undefined : byNumber.get(p.n);
    if (!c) return p.text;
    if (c.deleted || deletedIds.has(c.document_id)) return <span title="Deleted document">{p.text}</span>;
    const name = `Source ${c.n}: ${formatCitation(c)}${c.archived ? ", archived" : ""}`;
    return (
      <button
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
      {/* Markdown (DESIGN.md → Chat); react-markdown shows any HTML in the model's words as text. */}
      {text && (
        <div className={styles.answer}>
          <MarkerContext.Provider value={marker}>
            <Markdown remarkPlugins={remarkPlugins} components={components}>
              {text}
            </Markdown>
          </MarkerContext.Provider>
        </div>
      )}
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
