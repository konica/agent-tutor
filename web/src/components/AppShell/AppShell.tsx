import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useMatches, useNavigationType } from "react-router";

import { loadDocuments as defaultLoadDocuments } from "../../api/documents";
import { NAV } from "../../app/nav";
import { NeedsSubjectsContext, needsSubjectsLabel, useNeedsSubjectsState } from "../../app/needsSubjects";
import { SideNav } from "../SideNav/SideNav";
import { useNavCollapsed } from "../SideNav/useNavCollapsed";
import styles from "./AppShell.module.css";
import { NavRailContext } from "./NavRail";

type Handle = { wide?: boolean; bleed?: boolean } | undefined;

// A route opts into the wider column with `handle: { wide: true }` (the Library table needs it), or into
// `handle: { bleed: true }` to fill the whole main area and lay out its own panes (the chat).
export function AppShell({ loadDocuments = defaultLoadDocuments }: { loadDocuments?: typeof defaultLoadDocuments }) {
  const [collapsed, toggle] = useNavCollapsed();
  // A page can force the rail for a while (the chat's split view). The learner can still open the nav: that ends the
  // forcing without touching their saved choice.
  const [forced, setForced] = useState(false);
  const railed = collapsed || forced;
  // Forced over an expanded choice: one click just ends the forcing. Forced over a saved rail: the learner asked for the
  // nav, so the click also saves "expanded"; otherwise it would take two clicks to open.
  const onToggle = () => {
    if (forced) setForced(false);
    if (!forced || collapsed) toggle();
  };
  const matches = useMatches();
  const wide = matches.some((m) => (m.handle as Handle)?.wide);
  const bleed = matches.some((m) => (m.handle as Handle)?.bleed);
  const { pathname } = useLocation();
  const navigationType = useNavigationType();
  const main = useRef<HTMLElement>(null);
  const settledPage = useRef<string | null>(null);
  const needs = useNeedsSubjectsState(loadDocuments, pathname);
  // The page is the first path segment: /chat and a conversation's /chat/<id> are the same page, so the chat moving to
  // its new conversation's URL mid-answer neither moves focus nor changes the title.
  const page = `/${pathname.split("/")[1] ?? ""}`;

  useEffect(() => {
    const label = NAV.find((item) => item.path === page)?.label;
    document.title = label ? `${label} · Smart Tutor` : "Smart Tutor";
    // Move focus only when the learner went to another page: not on first load (StrictMode
    // runs this twice with the same path) and not on a redirect such as an unknown path → /library.
    const moved = settledPage.current !== null && settledPage.current !== page && navigationType !== "REPLACE";
    settledPage.current = page;
    if (moved) main.current?.focus();
  }, [page, navigationType]);

  return (
    <NavRailContext.Provider value={setForced}>
      <NeedsSubjectsContext.Provider value={needs}>
        <div className={railed ? `${styles.app} ${styles.collapsed}` : styles.app}>
          {/* recent is filled when the conversations list exists (US-5) */}
          <SideNav
            collapsed={railed}
            onToggle={onToggle}
            recent={[]}
            badges={needs.count ? { "/library": { count: needs.count, label: needsSubjectsLabel(needs.count) } } : undefined}
          />
          <main ref={main} className={styles.main} id="main-content" tabIndex={-1}>
            <div className={bleed ? styles.bleed : wide ? `${styles.page} ${styles.wide}` : styles.page}>
              <Outlet />
            </div>
          </main>
        </div>
      </NeedsSubjectsContext.Provider>
    </NavRailContext.Provider>
  );
}
