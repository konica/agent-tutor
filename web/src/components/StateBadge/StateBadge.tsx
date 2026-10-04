import { CircleAlert, CircleCheck, LoaderCircle, type LucideIcon } from "lucide-react";

import styles from "./StateBadge.module.css";

// Release 1 skeleton states; "choose subjects", "uploading" and "archived" arrive with their stories (DESIGN.md → Document states).
export type DocumentState = "processing" | "ready" | "failed";

const LOOK: Record<DocumentState, { label: string; icon: LucideIcon }> = {
  processing: { label: "Processing", icon: LoaderCircle },
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
