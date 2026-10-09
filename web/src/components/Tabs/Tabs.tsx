import { useRef, type KeyboardEvent } from "react";

import styles from "./Tabs.module.css";

type Tab<T extends string> = { value: T; label: string; count?: number };
type Props<T extends string> = { label: string; tabs: Tab<T>[]; value: T; onChange: (value: T) => void };

// A selector, not a panel switcher: the page's list is the panel (DESIGN.md → Components).
export function Tabs<T extends string>({ label, tabs, value, onChange }: Props<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const focused = buttons.current.findIndex((el) => el === document.activeElement);
    const current = focused >= 0 ? focused : tabs.findIndex((t) => t.value === value);
    const last = tabs.length - 1;
    const next =
      e.key === "ArrowRight" ? (current + 1) % tabs.length
      : e.key === "ArrowLeft" ? (current - 1 + tabs.length) % tabs.length
      : e.key === "Home" ? 0
      : e.key === "End" ? last
      : -1;
    if (next < 0) return;
    e.preventDefault();
    buttons.current[next]?.focus();
    onChange(tabs[next]!.value);
  };

  return (
    <div className={styles.tabs} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((tab, i) => {
        const selected = tab.value === value;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            ref={(el) => {
              buttons.current[i] = el;
            }}
            className={selected ? `${styles.tab} ${styles.selected}` : styles.tab}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.value)}
          >
            {tab.label}
            {tab.count !== undefined && <span className={styles.count}>{tab.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
