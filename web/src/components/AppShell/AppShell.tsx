import { useEffect, useRef } from "react";
import { Outlet, useLocation, useMatches, useNavigationType } from "react-router";

import { NAV } from "../../app/nav";
import { SideNav } from "../SideNav/SideNav";
import styles from "./AppShell.module.css";

// A route opts into the wider column with `handle: { wide: true }` (the Library table needs it).
export function AppShell() {
  const wide = useMatches().some((m) => (m.handle as { wide?: boolean } | undefined)?.wide);
  const { pathname } = useLocation();
  const navigationType = useNavigationType();
  const main = useRef<HTMLElement>(null);
  const settledPath = useRef<string | null>(null);

  useEffect(() => {
    const label = NAV.find((item) => item.path === pathname)?.label;
    document.title = label ? `${label} · Smart Tutor` : "Smart Tutor";
    // Move focus only when the learner went to another page: not on first load (StrictMode
    // runs this twice with the same path) and not on a redirect such as / → /library.
    const moved = settledPath.current !== null && settledPath.current !== pathname && navigationType !== "REPLACE";
    settledPath.current = pathname;
    if (moved) main.current?.focus();
  }, [pathname, navigationType]);

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
