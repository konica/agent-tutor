import { ChevronUp, LogOut } from "lucide-react";
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

import styles from "./UserMenu.module.css";

type Props = { name: string; detail?: string; onSignOut?: () => void };

const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]!.toUpperCase()).join("");

export function UserMenu({ name, detail, onSignOut }: Props) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const firstItem = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) firstItem.current?.focus();
  }, [open]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Escape" || !open) return;
    setOpen(false);
    toggle.current?.focus();
  };

  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    if (open && !root.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
  };

  return (
    <div className={styles.foot} ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
      {open && (
        <div className={styles.menu} id={menuId}>
          <div className={styles.head}>
            <strong>{name}</strong>
          </div>
          {onSignOut && (
            <button type="button" className={styles.item} ref={firstItem} onClick={onSignOut}>
              <LogOut className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
              Sign out
            </button>
          )}
        </div>
      )}
      <button
        type="button"
        ref={toggle}
        className={styles.user}
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={styles.avatar} aria-hidden="true">{initials(name)}</span>
        <span className={styles.who}>
          <span className={styles.name}>{name}</span>
          {detail && <span className={styles.detail}>{detail}</span>}
        </span>
        <ChevronUp className={`${styles.icon} ${open ? styles.flip : ""}`} strokeWidth={1.5} aria-hidden="true" />
      </button>
    </div>
  );
}
