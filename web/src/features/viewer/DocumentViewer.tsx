import { CircleAlert, Info, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type Ref } from "react";

import { recordHighlightMiss, type ChunkPassage } from "../../api/chunks";
import { restoreDocument, type DocumentFile, type DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import styles from "./DocumentViewer.module.css";
import { PassageHighlight } from "./PassageHighlight";
import type { PdfDoc, PdfLoader } from "./pdf";
import { useChunk, usePassageHighlight, usePassageReveal, type Highlight } from "./useChunk";
import { useDocumentFile } from "./useDocumentFile";
import { usePageFlip, type FlipDirection } from "./usePageFlip";
import { ViewerToolbar, ZOOM_STEPS } from "./ViewerToolbar";

/** A cited passage to show (PRD US-4b). Each new object means "jump to it", even for the same chunk. */
export type Passage = { chunkId: string; page: number };

type Props = {
  documentId: string;
  /** "pane": toolbar ends with Open in dialog + Close (X). "dialog": toolbar starts with a back/close text button. */
  mode: "pane" | "dialog";
  initialPage?: number; // default: the passage's page, else 1
  jumpTo?: { page: number }; // each new object moves to that page, keeping the loaded PDF (the pane, back from the dialog)
  passage?: Passage; // each new object moves to its page and highlights it there
  titleRef?: Ref<HTMLHeadingElement>; // the parent focuses it on open
  titleId?: string; // for aria-labelledby on the region/dialog
  onClose: () => void;
  closeLabel?: string; // dialog: "Back to side by side" (from the pane) or "Close"
  onOpenInDialog?: (page: number) => void; // pane only; shows the Open in dialog button when set
  openInDialogRef?: Ref<HTMLButtonElement>;
  onPageChange?: (page: number) => void;
  onRestored?: (document: DocumentResponse) => void; // the Library re-lists (the row leaves the Archived tab)
  showDetails?: boolean; // dialog: the details strip
  loadFile?: (id: string) => Promise<DocumentFile>; // tests
  loadPdfDoc?: PdfLoader; // tests
  restore?: (id: string) => Promise<DocumentResponse>; // tests
  loadChunk?: (id: string) => Promise<ChunkPassage>; // tests
  recordMiss?: () => void; // tests; the dialog opened from the pane passes a no-op (the pane counted that view)
};
export type DocumentViewerProps = Props;

// Loaded lazily so pdf.js stays out of the main bundle and out of tests that pass a fake loader.
const defaultLoadPdf: PdfLoader = (url) => import("./pdf").then((m) => m.loadPdf(url));
const defaultRestore = (id: string) => restoreDocument(id);
const defaultRecordMiss = () => recordHighlightMiss();

type PdfState = { status: "loading" } | { status: "ready"; doc: PdfDoc } | { status: "failed" };

// A new document remounts the viewer, so its page, zoom, and PDF never leak into the next one.
export function DocumentViewer(props: Props) {
  return <Viewer key={props.documentId} {...props} />;
}

function Viewer({
  documentId,
  mode,
  initialPage,
  jumpTo,
  passage,
  titleRef,
  titleId,
  onClose,
  closeLabel,
  onOpenInDialog,
  openInDialogRef,
  onPageChange,
  onRestored,
  showDetails = false,
  loadFile,
  loadPdfDoc = defaultLoadPdf,
  restore = defaultRestore,
  loadChunk,
  recordMiss = defaultRecordMiss,
}: Props) {
  const { state: file, retry, setDocument } = useDocumentFile(documentId, loadFile);
  const [pdf, setPdf] = useState<PdfState>({ status: "loading" });
  // An explicit initialPage wins: the dialog opened from the pane starts at the pane's page, which may not be the passage's.
  const [page, setPage] = useState(Math.max(1, initialPage ?? passage?.page ?? 1));
  const [zoom, setZoom] = useState(100);
  const [rendered, setRendered] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasAreaRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const renderChain = useRef<Promise<void>>(Promise.resolve());
  // Where a page reached by flipping opens: its top going down, its bottom going up, so reading continues (#212).
  const landAt = useRef<FlipDirection | null>(null);

  // The document stays known while Retry fetches a new link, so the title doesn't flicker back to "Document".
  const [document, setKnownDocument] = useState<DocumentResponse | null>(null);
  const current = file.status === "ready" ? file.file.document : null;
  if (current && current !== document) setKnownDocument(current);

  // The PDF loads from the first link only, and pdf.js fetches the rest of the file from that link in the background;
  // a renewed link (a new url) does not reload it and is not handed to pdf.js. So a fetch after the first link expires
  // fails: the error card shows, and Retry drops the link (file goes back to loading) so a fresh link loads it again.
  const url = file.status === "ready" ? file.file.url : null;
  const urlRef = useRef(url);
  urlRef.current = url;
  const loadPdfRef = useRef(loadPdfDoc);
  loadPdfRef.current = loadPdfDoc;
  const hasUrl = url !== null;

  useEffect(() => {
    if (!hasUrl) return;
    let live = true;
    let loaded: PdfDoc | null = null;
    setPdf({ status: "loading" });
    loadPdfRef.current(urlRef.current!).then(
      (doc) => {
        if (!live) return doc.destroy();
        loaded = doc;
        setPage((p) => Math.min(Math.max(1, p), doc.numPages));
        setPdf({ status: "ready", doc });
      },
      () => {
        if (live) setPdf({ status: "failed" });
      },
    );
    return () => {
      live = false;
      loaded?.destroy();
      setPdf({ status: "loading" });
    };
  }, [hasUrl]);

  const doc = pdf.status === "ready" ? pdf.doc : null;

  // pdf.js can't render twice into one canvas at once, so each render waits for the one before it.
  useEffect(() => {
    if (!doc) return;
    let live = true;
    const run = renderChain.current.then(async () => {
      if (!live) return;
      const pdfPage = await doc.page(page);
      if (!live || !canvasRef.current) return;
      const drawn = pdfPage.render(canvasRef.current, zoom / 100);
      // A flipped-to page lands once the canvas has its size, which render sets before it draws.
      const area = canvasAreaRef.current;
      if (landAt.current !== null && area) {
        area.scrollTop = landAt.current > 0 ? 0 : Math.max(0, area.scrollHeight - area.clientHeight);
        landAt.current = null;
      }
      await drawn;
      if (live) setRendered(true);
    });
    renderChain.current = run.catch(() => {});
    run.catch(() => {
      if (live) setPdf({ status: "failed" });
    });
    return () => {
      live = false;
    };
  }, [doc, page, zoom]);

  const numPages = doc?.numPages ?? null;

  // Whether the page changed since the passage opened; then the status goes back to "Page n of N".
  const [moved, setMoved] = useState(false);
  const [jumped, setJumped] = useState(jumpTo);
  if (jumpTo !== jumped) {
    setJumped(jumpTo);
    setMoved(true);
    if (jumpTo) setPage(Math.min(Math.max(1, jumpTo.page), numPages ?? Infinity));
  }
  const [opened, setOpened] = useState(passage);
  if (passage !== opened) {
    setOpened(passage);
    setMoved(false);
    if (passage) setPage(Math.min(Math.max(1, passage.page), numPages ?? Infinity));
  }

  const chunk = useChunk(passage?.chunkId, loadChunk);
  const highlight = usePassageHighlight(doc, page, chunk, passage, () => renderChain.current);
  const scale = zoom / 100;
  usePassageReveal(highlight, passage, scale, canvasAreaRef, pageRef, recordMiss);
  const boxes = highlight?.boxes ?? null;
  const missed = highlight !== null && boxes === null;

  const goTo = (next: number) => {
    if (numPages === null) return;
    const clamped = Math.min(Math.max(1, next), numPages);
    if (clamped === page) return;
    setPage(clamped);
    setMoved(true);
    onPageChange?.(clamped);
  };

  const flip = (dir: FlipDirection) => {
    if (numPages === null || page + dir < 1 || page + dir > numPages) return false;
    landAt.current = dir;
    goTo(page + dir);
    return true;
  };
  usePageFlip(canvasAreaRef, flip);

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "PageDown") {
      event.preventDefault();
      goTo(page + 1);
    } else if (event.key === "PageUp") {
      event.preventDefault();
      goTo(page - 1);
    }
  };

  const zoomBy = (step: 1 | -1) => {
    const i = ZOOM_STEPS.indexOf(zoom) + step;
    if (i >= 0 && i < ZOOM_STEPS.length) setZoom(ZOOM_STEPS[i]!);
  };

  const [restoring, setRestoring] = useState(false);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [restored, setRestored] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const focusTitle = useRef(false);
  // A restored document loses its Restore button; focus moves to the title rather than dropping to <body>.
  useEffect(() => {
    if (!focusTitle.current) return;
    focusTitle.current = false;
    root.current?.querySelector<HTMLElement>("h2")?.focus();
  }, [document]);
  const onRestore = () => {
    setRestoring(true);
    setRestoreFailed(false);
    restore(documentId).then(
      (updated) => {
        setRestoring(false);
        setRestored(true);
        focusTitle.current = true;
        setKnownDocument(updated);
        setDocument(updated);
        onRestored?.(updated);
      },
      () => {
        setRestoring(false);
        setRestoreFailed(true);
      },
    );
  };

  const failed = file.status === "failed" ? file.reason : pdf.status === "failed" ? "error" : null;

  return (
    <div ref={root} className={styles.viewer} onKeyDown={onKeyDown}>
      <ViewerToolbar
        mode={mode}
        title={document?.title ?? "Document"}
        titleRef={titleRef}
        titleId={titleId}
        archived={document?.archived ?? false}
        restoring={restoring}
        restoreFailed={restoreFailed}
        onRestore={onRestore}
        page={page}
        numPages={numPages}
        onPage={goTo}
        zoom={zoom}
        onZoom={zoomBy}
        closeLabel={closeLabel}
        onClose={onClose}
        onOpenInDialog={onOpenInDialog}
        openInDialogRef={openInDialogRef}
      />
      {showDetails && document && <Details document={document} numPages={numPages} />}
      <div ref={canvasAreaRef} className={styles.canvasArea}>
        {failed ? (
          <div className={styles.failure} role="alert">
            <CircleAlert className={styles.failureIcon} strokeWidth={1.5} aria-hidden="true" />
            <p className={styles.failureTitle}>We couldn't open this document.</p>
            {failed === "not-openable" ? (
              <p>This document can't be opened until it has been processed.</p>
            ) : failed === "not-found" ? (
              // Deleted (or never the learner's): a new link would 404 again, so there is no Retry.
              <p>This document is no longer in your library.</p>
            ) : (
              <>
                <p>Check your connection and try again.</p>
                <Button icon={RefreshCw} onClick={retry}>
                  Retry
                </Button>
              </>
            )}
          </div>
        ) : doc ? (
          <>
            {missed && (
              <p className={styles.note} role="note">
                <Info className={styles.noteIcon} strokeWidth={1.5} aria-hidden="true" />
                Couldn't highlight the passage on this page.
              </p>
            )}
            <div ref={pageRef} className={styles.page}>
              <canvas ref={canvasRef} role="img" aria-label={`Page ${page} of ${doc.numPages}`} />
              {boxes && chunk.status === "ready" && <PassageHighlight boxes={boxes} scale={scale} text={chunk.chunk.text} />}
            </div>
          </>
        ) : (
          <div className={styles.skeleton} aria-busy="true">
            <span className="visually-hidden">Loading document</span>
            <span className={`${styles.bar} ${styles.barTitle}`} />
            {Array.from({ length: 8 }, (_, i) => (
              <span key={i} className={styles.bar} />
            ))}
          </div>
        )}
      </div>
      <p className="visually-hidden" aria-live="polite">
        {status(rendered, page, numPages, passage !== undefined && !moved && page === passage.page, highlight)}
      </p>
      <p className="visually-hidden" aria-live="polite">
        {restored ? "Document restored." : ""}
      </p>
    </div>
  );
}

// The polite status line. While a just-opened passage is on screen it waits for the match (silent rather than announcing
// the page twice), then says how it went; otherwise it reads the page.
function status(rendered: boolean, page: number, numPages: number | null, opening: boolean, highlight: Highlight | null): string {
  if (numPages === null) return "";
  if (opening) {
    if (!highlight) return "";
    const result = highlight.boxes ? "Cited passage highlighted." : "Couldn't highlight the passage on this page.";
    return `Opened page ${page} of ${numPages}. ${result}`;
  }
  return rendered ? `Page ${page} of ${numPages}` : "";
}

function Details({ document, numPages }: { document: DocumentResponse; numPages: number | null }) {
  const facts = [document.authors.join(", "), document.year?.toString() ?? "", numPages !== null ? `${numPages} pages` : ""].filter(Boolean);
  return (
    <div className={styles.details}>
      {facts.map((fact) => (
        <span key={fact} className={styles.fact}>
          {fact}
        </span>
      ))}
      {document.subjects.map((s) => (
        <SubjectChip key={s.subject_id} name={s.name} hueKey={s.subject_id} size="sm" />
      ))}
      {document.archived && <span className={styles.fact}>Archived</span>}
    </div>
  );
}
