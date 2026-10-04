import { Outlet, useMatches } from "react-router";

import { SideNav } from "../SideNav/SideNav";
import styles from "./AppShell.module.css";

// A route opts into the wider column with `handle: { wide: true }` (the Library table needs it).
export function AppShell() {
  const wide = useMatches().some((m) => (m.handle as { wide?: boolean } | undefined)?.wide);
  return (
    <div className={styles.app}>
      <SideNav />
      <main className={styles.main} id="main-content" tabIndex={-1}>
        <div className={`${styles.page} ${wide ? styles.wide : ""}`}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
