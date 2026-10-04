import { CircleAlert, CircleCheck, ListChecks, LoaderCircle, type LucideIcon } from "lucide-react";

import styles from "./StateBadge.module.css";

// Release 1 states; "uploading" and "archived" arrive with their stories (DESIGN.md → Document states).
export type DocumentState = "processing" | "awaiting_subjects" | "ready" | "failed";

const LOOK: Record<DocumentState, { label: string; icon: LucideIcon }> = {
  processing: { label: "Processing", icon: LoaderCircle },
  awaiting_subjects: { label: "Choose subjects", icon: ListChecks },
  ready: { label: "Ready", icon: CircleCheck },
  failed: { label: "Failed", icon: CircleAlert },
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
