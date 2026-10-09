import { MoreHorizontal, type LucideIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

import { IconButton } from "../Button/IconButton";
import styles from "./RowMenu.module.css";

type Item = { label: string; icon: LucideIcon; onSelect: () => void; danger?: boolean };
type Props = { label: string; items: Item[] };

// The "More" menu at the end of a list row.
export function RowMenu({ label, items }: Props) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const entries = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (open) entries.current[0]?.focus();
  }, [open]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return;
    if (e.key === "Escape") {
      setOpen(false);
      toggle.current?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const at = entries.current.findIndex((el) => el === document.activeElement);
    const step = e.key === "ArrowDown" ? 1 : -1;
    entries.current[(at + step + items.length) % items.length]?.focus();
  };

  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    if (open && !root.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
  };

  return (
    <div className={styles.root} ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
      <IconButton
        ref={toggle}
        label={label}
        icon={MoreHorizontal}
        tip={!open}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
      />
      {open && (
        <div className={styles.menu} id={menuId} role="menu" aria-label={label}>
          {items.map((item, i) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              ref={(el) => {
                entries.current[i] = el;
              }}
              className={item.danger ? `${styles.item} ${styles.danger}` : styles.item}
              onClick={() => {
                setOpen(false);
                toggle.current?.focus();
                item.onSelect();
              }}
            >
              <item.icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
