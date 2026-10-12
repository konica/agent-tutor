import { Archive, Filter, Info, MessageSquare, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";

import {
  archiveConversation,
  hasConversationFilters,
  listConversations,
  restoreConversation,
  type ConversationFilters as Filters,
  type ThreadSummaryResponse,
} from "../../api/conversations";
import type { SubjectResponse } from "../../api/generated/types.gen";
import { loadMySubjects } from "../../api/subjects";
import { conversationTitle, useConversations } from "../../app/conversations";
import { NAV } from "../../app/nav";
import { SessionExpiredError } from "../../auth/authClient";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { Tabs } from "../../components/Tabs/Tabs";
import { ConversationFilters } from "./ConversationFilters";
import { ConversationTable } from "./ConversationTable";
import styles from "./ConversationsPage.module.css";
import { useFilteredConversations } from "./useFilteredConversations";

type View = "active" | "archived";
const ARCHIVED_NOTICE = "Archived conversations stay readable. Restore one to keep asking.";
const defaultLoadArchived = () => listConversations({ archived: true });
const defaultLoadSubjects = () => loadMySubjects();

type Props = {
  /** Loads the conversations matching the filters, active or archived. */
  loadConversations?: (filters: Filters & { archived?: boolean }) => Promise<ThreadSummaryResponse[]>;
  loadArchived?: () => Promise<ThreadSummaryResponse[]>;
  loadSubjects?: () => Promise<SubjectResponse[]>;
  archive?: (threadId: string) => Promise<unknown>;
  restore?: (threadId: string) => Promise<unknown>;
};

// The learner's conversations (PRD US-13): active ones from the app shell, which reloads them on every navigation and
// feeds the side nav too, and archived ones loaded here. While filters are set this page loads the matching ones of the
// shown tab itself, so the side nav keeps the most recent unfiltered. A row's menu archives or restores it.
export function ConversationsPage({
  loadConversations = listConversations,
  loadArchived = defaultLoadArchived,
  loadSubjects = defaultLoadSubjects,
  archive = archiveConversation,
  restore = restoreConversation,
}: Props = {}) {
  const { list, failed, refresh } = useConversations();
  const navigate = useNavigate();
  const [view, setView] = useState<View>("active");
  const [archived, setArchived] = useState<ThreadSummaryResponse[] | null>(null);
  const [archivedFailed, setArchivedFailed] = useState(false);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [status, setStatus] = useState("");
  const [filters, setFilters] = useState<Filters>({});
  const [subjects, setSubjects] = useState<SubjectResponse[]>([]);
  const statusRegion = useRef<HTMLParagraphElement>(null);
  const loadRef = useRef(loadArchived);
  const latest = useRef(0);
  useEffect(() => {
    loadRef.current = loadArchived; // an inline `loadArchived` must not reload
  }, [loadArchived]);

  useEffect(() => {
    let alive = true;
    loadSubjects().then((s) => alive && setSubjects(s), () => {}); // the Subject filter just stays empty
    return () => {
      alive = false;
    };
  }, [loadSubjects]);

  // Only the latest answer is applied, and a failure keeps the last list.
  const reloadArchived = useCallback(async () => {
    const call = ++latest.current;
    try {
      const items = await loadRef.current();
      if (call !== latest.current) return;
      setArchived(items);
      setArchivedFailed(false);
    } catch {
      if (call === latest.current) setArchivedFailed(true); // a 401 is handled by the API client; a failure keeps the last list
    }
  }, []);
  useEffect(() => {
    void reloadArchived();
    return () => {
      latest.current++; // unmounted: ignore loads still running
    };
  }, [reloadArchived]);

  const archivedView = view === "archived";
  // The filters narrow the tab shown. Switching tabs, or either list changing (an archive, a restore, the shell's
  // reload), loads the matching ones again.
  const loadFiltered = useCallback((f: Filters) => loadConversations({ ...f, archived: archivedView }), [loadConversations, archivedView]);
  const reloadKey = useMemo(() => ({ view, list, archived }), [view, list, archived]);
  const filtering = hasConversationFilters(filters);
  const filtered = useFilteredConversations(loadFiltered, filters, reloadKey);
  const clear = () => setFilters({});

  async function change(t: ThreadSummaryResponse, archiving: boolean) {
    const title = conversationTitle(t);
    let moved = false; // the row left this list, and its menu with it
    setBusy((s) => new Set(s).add(t.thread_id));
    try {
      await (archiving ? archive : restore)(t.thread_id);
      moved = true;
      setStatus(archiving ? `${title} archived. Find it under Archived.` : `${title} restored.`);
    } catch (error) {
      // A 401 is left to the session screen.
      if (!(error instanceof SessionExpiredError)) setStatus(`Couldn't ${archiving ? "archive" : "restore"} ${title}. Try again.`);
    }
    refresh(); // the shell's active list: this page's Active tab and the side nav's recent ones
    await reloadArchived();
    setBusy((s) => {
      const next = new Set(s);
      next.delete(t.thread_id);
      return next;
    });
    // On failure the row keeps focus, unless the disabled menu button dropped it.
    if (moved || document.activeElement === document.body) statusRegion.current?.focus();
  }

  const start = () => navigate("/chat");
  const description = NAV.find((item) => item.path === "/conversations")?.description;
  const shown = filtering ? filtered.list : archivedView ? archived : list;
  // Without the archived list (its load failed), an empty Active list still gets the plain "No conversations yet".
  const bothEmpty = list?.length === 0 && (archived?.length === 0 || (archived === null && archivedFailed));
  const waiting = list?.length === 0 && archived === null && !archivedFailed; // an empty Active tab says nothing until Archived is known
  const toolbar = list && !bothEmpty && !waiting;
  return (
    <>
      <PageHeader
        title="Conversations"
        count={list ? `${list.length} ${list.length === 1 ? "conversation" : "conversations"}` : undefined}
        description={description}
        actions={<Button variant="primary" icon={Plus} onClick={start}>New conversation</Button>}
      />
      <p ref={statusRegion} tabIndex={-1} role="status" aria-live="polite" className="visually-hidden">
        {status}
      </p>
      {failed && list === null && <p className={styles.error}>Can't load your conversations. Reload the page to try again.</p>}
      {toolbar && (
        <div className={styles.toolbar}>
          <Tabs
            label="Conversations view"
            tabs={[
              { value: "active", label: "Active", count: list.length },
              { value: "archived", label: "Archived", count: archived?.length },
            ]}
            value={view}
            onChange={setView}
          />
          <ConversationFilters filters={filters} onChange={setFilters} subjects={subjects} count={shown ? shown.length : null} onClear={clear} />
        </div>
      )}
      {toolbar && archivedView && (
        <p className={styles.notice}>
          <Info aria-hidden="true" strokeWidth={1.5} />
          {ARCHIVED_NOTICE}
        </p>
      )}
      {list && archivedView && !filtering && archived === null && archivedFailed && !bothEmpty && (
        <p className={styles.error}>Can't load your archived conversations. Reload the page to try again.</p>
      )}
      {filtering && filtered.failed && <p className={styles.error}>Can't load your conversations. Reload the page to try again.</p>}
      {bothEmpty && (
        <EmptyState icon={MessageSquare} title="No conversations yet" actions={<Button variant="primary" icon={Plus} onClick={start}>Start a conversation</Button>}>
          <p>Ask a question about your documents. Every conversation is saved here so you can come back to it.</p>
        </EmptyState>
      )}
      {toolbar && filtering && shown?.length === 0 && (
        <EmptyState icon={Filter} title="No conversations match these filters" actions={<Button onClick={clear}>Clear filters</Button>}>
          <p>Try another subject, a wider date range or another search.</p>
        </EmptyState>
      )}
      {toolbar && !filtering && archivedView && archived?.length === 0 && (
        <EmptyState icon={Archive} title="No archived conversations">
          <p>Conversations you archive appear here. You can restore them at any time.</p>
        </EmptyState>
      )}
      {toolbar && !filtering && !archivedView && list.length === 0 && (
        <EmptyState icon={MessageSquare} title="No active conversations" actions={<Button variant="primary" icon={Plus} onClick={start}>Start a conversation</Button>}>
          <p>Start a new conversation, or restore one from Archived.</p>
        </EmptyState>
      )}
      {list && shown && shown.length > 0 && (
        <ConversationTable
          conversations={shown}
          archived={archivedView}
          onArchive={(t) => void change(t, true)}
          onRestore={(t) => void change(t, false)}
          busy={busy}
        />
      )}
    </>
  );
}
