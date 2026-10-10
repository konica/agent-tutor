import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { DocumentViewer, type Passage } from "./DocumentViewer";
import styles from "./DocumentPane.module.css";
import { ViewerDialog, type ViewerDeps } from "./ViewerDialog";

type Props = { documentId: string; onClose: () => void; viewerDeps?: ViewerDeps; passage?: Passage };

// The pane already counted a passage it couldn't highlight; the dialog showing the same passage doesn't count it again.
const countedByPane = () => {};

// The document beside the conversation (DESIGN.md → Chat, Split view): a labelled region, not a modal. Focus goes to
// the title on open and on every swap; Escape closes it. "Open in dialog" shows the same page and highlight in the
// overlay; closing the overlay brings the pane to the overlay's last page and focus back to the button.
export function DocumentPane({ documentId, onClose, viewerDeps, passage }: Props) {
  const titleId = useId();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const openInDialogRef = useRef<HTMLButtonElement>(null);
  const [dialogPage, setDialogPage] = useState<number | null>(null);
  // A new object per close, so the pane moves even when the page number equals the last jump's.
  const [jumpTo, setJumpTo] = useState<{ page: number }>();

  // Runs after the swapped-in viewer has committed, so this is the new document's heading.
  useEffect(() => {
    titleRef.current?.focus();
  }, [documentId]);

  // A child that handles Escape (the dialog) stops it, so it never reaches here.
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") onClose();
  };

  const closeDialog = (page: number) => {
    setDialogPage(null);
    setJumpTo({ page });
  };

  return (
    <section className={styles.pane} aria-labelledby={titleId} onKeyDown={onKeyDown}>
      <DocumentViewer
        documentId={documentId}
        mode="pane"
        jumpTo={jumpTo}
        passage={passage}
        titleRef={titleRef}
        titleId={titleId}
        onClose={onClose}
        onOpenInDialog={setDialogPage}
        openInDialogRef={openInDialogRef}
        {...viewerDeps}
      />
      {dialogPage !== null && (
        <ViewerDialog
          documentId={documentId}
          initialPage={dialogPage}
          passage={passage}
          closeLabel="Back to side by side"
          onClose={closeDialog}
          returnFocusTo={openInDialogRef}
          viewerDeps={{ ...viewerDeps, recordMiss: countedByPane }}
        />
      )}
    </section>
  );
}
