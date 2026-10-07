import { ChevronDown, ChevronUp, CircleAlert, CircleCheck, FileText, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import styles from "./UploadTray.module.css";

export type TrayItem = { id: string; name: string; size: string; status: "uploading" | "uploaded" | "failed"; progress: number };

const files = (n: number) => `${n} ${n === 1 ? "file" : "files"}`;

// Fixed bottom right and non-blocking (DESIGN.md → Layout). Results are announced by the page's live region, not here.
export function UploadTray({ items, onClose }: { items: TrayItem[]; onClose: () => void }) {
  const headingId = useId();
  const [collapsed, setCollapsed] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const closeFocused = useRef(false);
  const busy = items.filter((t) => t.status === "uploading").length;
  const empty = items.length === 0;

  // Close is hidden while uploads run; if it had focus when a new upload began, the toggle takes it.
  useEffect(() => {
    if (busy > 0 && closeFocused.current) toggle.current?.focus();
    closeFocused.current = false;
  }, [busy]);
  useEffect(() => {
    if (empty) setCollapsed(false); // the next batch opens expanded
  }, [empty]);
  if (empty) return null;
  const Toggle = collapsed ? ChevronUp : ChevronDown;
  return (
    <section className={styles.tray} aria-labelledby={headingId}>
      <div className={styles.head}>
        <strong id={headingId} className={styles.heading}>
          {busy ? `Uploading ${files(busy)}…` : `Uploads · ${files(items.length)}`}
        </strong>
        <button ref={toggle} type="button" className={styles.iconButton} aria-expanded={!collapsed} aria-label={collapsed ? "Expand uploads" : "Collapse uploads"} onClick={() => setCollapsed((c) => !c)}>
          <Toggle strokeWidth={1.5} aria-hidden="true" />
        </button>
        {!busy && (
          <button type="button" className={styles.iconButton} aria-label="Close uploads" onClick={onClose} onFocus={() => (closeFocused.current = true)} onBlur={() => (closeFocused.current = false)}>
            <X strokeWidth={1.5} aria-hidden="true" />
          </button>
        )}
      </div>
      {!collapsed && (
        <ul className={styles.list}>
          {items.map((t) => (
            <TrayRow key={t.id} item={t} />
          ))}
        </ul>
      )}
    </section>
  );
}

function TrayRow({ item }: { item: TrayItem }) {
  const Icon = item.status === "uploaded" ? CircleCheck : item.status === "failed" ? CircleAlert : FileText;
  const status = item.status === "uploading" ? `Uploading · ${item.size}` : item.status === "uploaded" ? "Uploaded · processing" : "Upload failed";
  const percent = Math.round(item.progress * 100);
  return (
    <li className={`${styles.item} ${styles[item.status] ?? ""}`}>
      <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      <div className={styles.text}>
        <span className={styles.name}>{item.name}</span>
        <span className={styles.status}>{status}</span>
        {item.status === "uploading" && (
          <div className={styles.bar} role="progressbar" aria-label={`Upload progress for ${item.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
            <span style={{ transform: `scaleX(${item.progress})` }} />
          </div>
        )}
      </div>
    </li>
  );
}
