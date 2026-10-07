import { Upload } from "lucide-react";

import styles from "./DropOverlay.module.css";

// Visual only: the keyboard path is the Upload button, and the drop result is announced by the page's live region.
export function DropOverlay() {
  return (
    <div className={styles.overlay} aria-hidden="true">
      <div className={styles.label}>
        <Upload className={styles.icon} strokeWidth={1.5} />
        Drop PDFs to upload
      </div>
    </div>
  );
}
