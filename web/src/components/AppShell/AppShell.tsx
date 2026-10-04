import { Outlet } from "react-router";

import { SideNav } from "../SideNav/SideNav";
import styles from "./AppShell.module.css";

export function AppShell() {
  return (
    <div className={styles.app}>
      <SideNav />
      <main className={styles.main} id="main-content" tabIndex={-1}>
        <div className={styles.page}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
