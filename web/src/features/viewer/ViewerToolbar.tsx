import { Archive, ArrowLeft, ChevronLeft, CircleAlert, ChevronRight, Maximize2, Minus, Plus, RotateCcw, X } from "lucide-react";
import type { Ref } from "react";

import { Button } from "../../components/Button/Button";
import { IconButton } from "../../components/Button/IconButton";
import styles from "./DocumentViewer.module.css";

export const ZOOM_STEPS = [50, 75, 100, 125, 150, 200];

type Props = {
  mode: "pane" | "dialog";
  title: string;
  titleRef?: Ref<HTMLHeadingElement>;
  titleId?: string;
  archived: boolean;
  restoring: boolean;
  restoreFailed: boolean;
  onRestore: () => void;
  page: number;
  numPages: number | null; // null until the PDF has loaded
  onPage: (page: number) => void;
  zoom: number;
  onZoom: (step: 1 | -1) => void;
  closeLabel?: string;
  onClose: () => void;
  onOpenInDialog?: (page: number) => void;
  openInDialogRef?: Ref<HTMLButtonElement>;
};

// A control that can't act right now (the first or last page, the smallest or largest zoom, a restore in flight) is
// aria-disabled with no click, never natively disabled: a disabled button drops keyboard focus to <body>, so Enter on
// Next at the second-last page would escape the dialog's focus trap and stop the pane's Escape and PageUp/PageDown.
function unless(off: boolean, act: () => void) {
  return { "aria-disabled": off || undefined, onClick: off ? undefined : act };
}

// The viewer's one 40px row (DESIGN.md → Chat, Split view). No download button.
export function ViewerToolbar(p: Props) {
  const back = p.closeLabel ?? "Close";
  return (
    <div className={styles.toolbar}>
      {p.mode === "dialog" && (
        <Button variant="quiet" size="sm" icon={back === "Close" ? X : ArrowLeft} onClick={p.onClose}>
          {back}
        </Button>
      )}
      <h2 className={styles.title} ref={p.titleRef} id={p.titleId} tabIndex={-1} title={p.title}>
        {p.title}
      </h2>
      {p.archived && (
        <>
          <span className={styles.archived}>
            <Archive className={styles.badgeIcon} strokeWidth={1.5} aria-hidden="true" />
            Archived · read-only
          </span>
          <Button size="sm" icon={RotateCcw} {...unless(p.restoring, p.onRestore)}>
            Restore
          </Button>
          {p.restoreFailed && (
            <span className={styles.restoreError} role="alert">
              <CircleAlert className={styles.badgeIcon} strokeWidth={1.5} aria-hidden="true" />
              Couldn't restore. Try again.
            </span>
          )}
        </>
      )}
      <div className={styles.controls}>
        <IconButton label="Previous page" icon={ChevronLeft} {...unless(p.numPages === null || p.page <= 1, () => p.onPage(p.page - 1))} />
        <span className={styles.readout}>{p.numPages === null ? `p. ${p.page}` : `p. ${p.page} / ${p.numPages}`}</span>
        <IconButton
          label="Next page"
          icon={ChevronRight}
          {...unless(p.numPages === null || p.page >= p.numPages, () => p.onPage(p.page + 1))}
        />
        <span className={styles.separator} aria-hidden="true" />
        <IconButton label="Zoom out" icon={Minus} {...unless(p.zoom <= ZOOM_STEPS[0]!, () => p.onZoom(-1))} />
        <span className={styles.readout}>{p.zoom}%</span>
        <IconButton label="Zoom in" icon={Plus} {...unless(p.zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1]!, () => p.onZoom(1))} />
        {p.mode === "pane" && (
          <>
            <span className={styles.separator} aria-hidden="true" />
            {p.onOpenInDialog && (
              <IconButton label="Open in dialog" icon={Maximize2} ref={p.openInDialogRef} onClick={() => p.onOpenInDialog?.(p.page)} />
            )}
            <IconButton label="Close" icon={X} onClick={p.onClose} />
          </>
        )}
      </div>
    </div>
  );
}
