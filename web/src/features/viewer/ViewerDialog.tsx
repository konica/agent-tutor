import { useId, useRef, type RefObject } from "react";
import { createPortal } from "react-dom";

import { useModal } from "../../components/Dialog/useModal";
import { DocumentViewer, type DocumentViewerProps } from "./DocumentViewer";
import styles from "./ViewerDialog.module.css";

/** Test seams passed through to DocumentViewer. */
export type ViewerDeps = Pick<DocumentViewerProps, "loadFile" | "loadPdfDoc" | "restore">;

type Props = {
  documentId: string;
  initialPage?: number;
  closeLabel: string; // "Back to side by side" from the pane, else "Close"
  onClose: (page: number) => void; // with the page the learner was on
  returnFocusTo?: RefObject<HTMLElement | null>;
  viewerDeps?: ViewerDeps;
};

// The viewer as an overlay of --viewer-w (DESIGN.md → Chat, Split view): a modal with the details strip. Focus starts on
// the title, Tab stays in, Escape closes it alone. Portalled to <body> so no ancestor's layout can clip or contain it.
export function ViewerDialog({ documentId, initialPage = 1, closeLabel, onClose, returnFocusTo, viewerDeps }: Props) {
  const titleId = useId();
  const page = useRef(initialPage);
  const close = () => onClose(page.current);
  const { ref, onKeyDown } = useModal(close, returnFocusTo);
  // The title is a tabIndex=-1 heading, so the trap finds it by data-autofocus.
  const markTitle = (title: HTMLHeadingElement | null) => title?.setAttribute("data-autofocus", "");

  return createPortal(
    <div className={styles.scrim}>
      <div ref={ref} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <DocumentViewer
          documentId={documentId}
          mode="dialog"
          initialPage={initialPage}
          titleRef={markTitle}
          titleId={titleId}
          closeLabel={closeLabel}
          onClose={close}
          onPageChange={(p) => (page.current = p)}
          showDetails
          {...viewerDeps}
        />
      </div>
    </div>,
    document.body,
  );
}
