import { Archive, CircleAlert, CircleCheck, ListChecks, LoaderCircle, Upload, type LucideIcon } from "lucide-react";

import styles from "./StateBadge.module.css";

// Release 1 states, plus "uploading" while the browser still sends the file, and "archived" (a flag on any state; DESIGN.md → Document states).
export type DocumentState = "uploading" | "processing" | "awaiting_subjects" | "ready" | "failed" | "archived";

const LOOK: Record<DocumentState, { label: string; icon: LucideIcon }> = {
  uploading: { label: "Uploading", icon: Upload },
  processing: { label: "Processing", icon: LoaderCircle },
  awaiting_subjects: { label: "Choose subjects", icon: ListChecks },
  ready: { label: "Ready", icon: CircleCheck },
  failed: { label: "Failed", icon: CircleAlert },
  archived: { label: "Archived", icon: Archive },
};

export function StateBadge({ state }: { state: DocumentState }) {
  const { label, icon: Icon } = LOOK[state];
  return (
    <span className={`${styles.state} ${styles[state]}`}>
      <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      {label}
    </span>
  );
}
