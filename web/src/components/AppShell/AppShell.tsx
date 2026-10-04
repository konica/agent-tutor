import { useEffect, useRef } from "react";
import { Outlet, useLocation, useMatches } from "react-router";

import { NAV } from "../../app/nav";

import { SideNav } from "../SideNav/SideNav";
import styles from "./AppShell.module.css";

// A route opts into the wider column with `handle: { wide: true }` (the Library table needs it).
export function AppShell() {
  const wide = useMatches().some((m) => (m.handle as { wide?: boolean } | undefined)?.wide);
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);

  useEffect(() => {
    const label = NAV.find((item) => item.path === pathname)?.label;
    document.title = label ? `${label} · Smart Tutor` : "Smart Tutor";
    if (first.current) first.current = false;
    else main.current?.focus();
  }, [pathname]);

  return (
    <div className={styles.app}>
      <SideNav />
      <main ref={main} className={styles.main} id="main-content" tabIndex={-1}>
        <div className={`${styles.page} ${wide ? styles.wide : ""}`}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
