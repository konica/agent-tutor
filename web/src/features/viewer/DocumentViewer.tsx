import { CircleAlert, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type Ref } from "react";

import { restoreDocument, type DocumentFile, type DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import styles from "./DocumentViewer.module.css";
import type { PdfDoc, PdfLoader } from "./pdf";
import { useDocumentFile } from "./useDocumentFile";
import { ViewerToolbar, ZOOM_STEPS } from "./ViewerToolbar";

type Props = {
  documentId: string;
  /** "pane": toolbar ends with Open in dialog + Close (X). "dialog": toolbar starts with a back/close text button. */
  mode: "pane" | "dialog";
  initialPage?: number; // default 1
  titleRef?: Ref<HTMLHeadingElement>; // the parent focuses it on open
  titleId?: string; // for aria-labelledby on the region/dialog
  onClose: () => void;
  closeLabel?: string; // dialog: "Back to side by side" (from the pane) or "Close"
  onOpenInDialog?: (page: number) => void; // pane only; shows the Open in dialog button when set
  openInDialogRef?: Ref<HTMLButtonElement>;
  onPageChange?: (page: number) => void;
  showDetails?: boolean; // dialog: the details strip
  loadFile?: (id: string) => Promise<DocumentFile>; // tests
  loadPdfDoc?: PdfLoader; // tests
  restore?: (id: string) => Promise<DocumentResponse>; // tests
};
export type DocumentViewerProps = Props;

// Loaded lazily so pdf.js stays out of the main bundle and out of tests that pass a fake loader.
const defaultLoadPdf: PdfLoader = (url) => import("./pdf").then((m) => m.loadPdf(url));
const defaultRestore = (id: string) => restoreDocument(id);

type PdfState = { status: "loading" } | { status: "ready"; doc: PdfDoc } | { status: "failed" };

// A new document remounts the viewer, so its page, zoom, and PDF never leak into the next one.
export function DocumentViewer(props: Props) {
  return <Viewer key={props.documentId} {...props} />;
}

function Viewer({
  documentId,
  mode,
  initialPage = 1,
  titleRef,
  titleId,
  onClose,
  closeLabel,
  onOpenInDialog,
  openInDialogRef,
  onPageChange,
  showDetails = false,
  loadFile,
  loadPdfDoc = defaultLoadPdf,
  restore = defaultRestore,
}: Props) {
  const { state: file, retry, setDocument } = useDocumentFile(documentId, loadFile);
  const [pdf, setPdf] = useState<PdfState>({ status: "loading" });
  const [page, setPage] = useState(Math.max(1, initialPage));
  const [zoom, setZoom] = useState(100);
  const [rendered, setRendered] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderChain = useRef<Promise<void>>(Promise.resolve());

  // The document stays known while Retry fetches a new link, so the title doesn't flicker back to "Document".
  const [document, setKnownDocument] = useState<DocumentResponse | null>(null);
  const current = file.status === "ready" ? file.file.document : null;
  if (current && current !== document) setKnownDocument(current);

  // The PDF loads from the first link only: a renewed link (a new url) must not reload it. Retry drops the link
  // (file goes back to loading), so the next link loads it again.
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
      await pdfPage.render(canvasRef.current, zoom / 100);
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

  const goTo = (next: number) => {
    if (numPages === null) return;
    const clamped = Math.min(Math.max(1, next), numPages);
    if (clamped === page) return;
    setPage(clamped);
    onPageChange?.(clamped);
  };

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
  const onRestore = () => {
    setRestoring(true);
    setRestoreFailed(false);
    restore(documentId).then(
      (updated) => {
        setRestoring(false);
        setKnownDocument(updated);
        setDocument(updated);
      },
      () => {
        setRestoring(false);
        setRestoreFailed(true);
      },
    );
  };

  const failed = file.status === "failed" ? file.reason : pdf.status === "failed" ? "error" : null;

  return (
    <div className={styles.viewer} onKeyDown={onKeyDown}>
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
      <div className={styles.canvasArea}>
        {failed ? (
          <div className={styles.failure} role="alert">
            <CircleAlert className={styles.failureIcon} strokeWidth={1.5} aria-hidden="true" />
            <p className={styles.failureTitle}>We couldn't open this document.</p>
            {failed === "not-openable" ? (
              <p>This document can't be opened until it has been processed.</p>
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
          <div className={styles.page}>
            <canvas ref={canvasRef} />
          </div>
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
        {rendered && numPages !== null ? `Page ${page} of ${numPages}` : ""}
      </p>
    </div>
  );
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
