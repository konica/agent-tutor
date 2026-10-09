import { ChevronDown, ChevronUp, CircleAlert, CircleCheck, FileText, Info, RotateCcw, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "../Button/Button";
import styles from "./UploadTray.module.css";

// "already": the server found the learner already has this file (PRD D19); documentId is their existing document.
export type TrayItem = {
  id: string;
  name: string;
  size: string;
  status: "uploading" | "uploaded" | "failed" | "already";
  progress: number;
  documentId?: string;
  archived?: boolean;
};

const ICONS = { uploading: FileText, uploaded: CircleCheck, failed: CircleAlert, already: Info } as const;

function statusText(item: TrayItem): string {
  switch (item.status) {
    case "uploading":
      return `Uploading · ${item.size}`;
    case "uploaded":
      return "Uploaded · processing";
    case "failed":
      return "Upload failed";
    case "already":
      return item.archived ? "Already in your library, archived" : "Already in your library";
  }
}

const files = (n: number) => `${n} ${n === 1 ? "file" : "files"}`;

// Fixed bottom right and non-blocking (DESIGN.md → Layout). Results are announced by the page's live region, not here.
export function UploadTray({ items, onClose, onRestore }: { items: TrayItem[]; onClose: () => void; onRestore?: (item: TrayItem) => void }) {
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
            <TrayRow key={t.id} item={t} onRestore={onRestore} />
          ))}
        </ul>
      )}
    </section>
  );
}

function TrayRow({ item, onRestore }: { item: TrayItem; onRestore?: (item: TrayItem) => void }) {
  const Icon = ICONS[item.status];
  const percent = Math.round(item.progress * 100);
  return (
    <li className={`${styles.item} ${styles[item.status] ?? ""}`}>
      <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      <div className={styles.text}>
        <span className={styles.name}>{item.name}</span>
        <span className={styles.status}>{statusText(item)}</span>
        {/* An archived document is not in the Active list, so it gets Restore instead of a link. */}
        {item.status === "already" && item.archived && item.documentId && onRestore && (
          <Button size="sm" icon={RotateCcw} className={styles.restore} aria-label={`Restore ${item.name}`} onClick={() => onRestore(item)}>
            Restore
          </Button>
        )}
        {item.status === "already" && !item.archived && item.documentId && (
          <a className={styles.link} href={`#document-${item.documentId}`}>
            Open document
          </a>
        )}
        {item.status === "uploading" && (
          <div className={styles.bar} role="progressbar" aria-label={`Upload progress for ${item.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
            <span style={{ transform: `scaleX(${item.progress})` }} />
          </div>
        )}
      </div>
    </li>
  );
}
