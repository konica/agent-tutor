import { Archive, Info, MessageSquare, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { archiveConversation, listConversations, restoreConversation, type ThreadSummaryResponse } from "../../api/conversations";
import { conversationTitle, useConversations } from "../../app/conversations";
import { NAV } from "../../app/nav";
import { SessionExpiredError } from "../../auth/authClient";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { Tabs } from "../../components/Tabs/Tabs";
import { ConversationTable } from "./ConversationTable";
import styles from "./ConversationsPage.module.css";

type View = "active" | "archived";
const ARCHIVED_NOTICE = "Archived conversations stay readable. Restore one to keep asking.";
const defaultLoadArchived = () => listConversations({ archived: true });

type Props = {
  loadArchived?: () => Promise<ThreadSummaryResponse[]>;
  archive?: (threadId: string) => Promise<unknown>;
  restore?: (threadId: string) => Promise<unknown>;
};

// The learner's conversations (PRD US-13): active ones from the app shell, which reloads them on every navigation and
// feeds the side nav too, and archived ones loaded here. A row's menu archives or restores it.
export function ConversationsPage({ loadArchived = defaultLoadArchived, archive = archiveConversation, restore = restoreConversation }: Props) {
  const { list, failed, refresh } = useConversations();
  const navigate = useNavigate();
  const [view, setView] = useState<View>("active");
  const [archived, setArchived] = useState<ThreadSummaryResponse[] | null>(null);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [status, setStatus] = useState("");
  const statusRegion = useRef<HTMLParagraphElement>(null);
  const loadRef = useRef(loadArchived);
  const latest = useRef(0);
  useEffect(() => {
    loadRef.current = loadArchived; // an inline `loadArchived` must not reload
  }, [loadArchived]);

  // Only the latest answer is applied, and a failure keeps the last list.
  const reloadArchived = useCallback(async () => {
    const call = ++latest.current;
    try {
      const items = await loadRef.current();
      if (call === latest.current) setArchived(items);
    } catch {
      // a 401 is handled by the API client
    }
  }, []);
  useEffect(() => {
    void reloadArchived();
    return () => {
      latest.current++; // unmounted: ignore loads still running
    };
  }, [reloadArchived]);

  async function change(t: ThreadSummaryResponse, archiving: boolean) {
    const title = conversationTitle(t);
    setBusy((s) => new Set(s).add(t.thread_id));
    try {
      await (archiving ? archive : restore)(t.thread_id);
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
    statusRegion.current?.focus(); // the row left this list, and its menu with it
  }

  const start = () => navigate("/chat");
  const description = NAV.find((item) => item.path === "/conversations")?.description;
  const archivedView = view === "archived";
  const shown = archivedView ? archived : list;
  const bothEmpty = list?.length === 0 && archived?.length === 0;
  const waiting = list?.length === 0 && archived === null; // an empty Active tab says nothing until Archived is known
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
      {list && !bothEmpty && !waiting && (
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
        </div>
      )}
      {list && !bothEmpty && !waiting && archivedView && (
        <p className={styles.notice}>
          <Info aria-hidden="true" strokeWidth={1.5} />
          {ARCHIVED_NOTICE}
        </p>
      )}
      {bothEmpty && (
        <EmptyState icon={MessageSquare} title="No conversations yet" actions={<Button variant="primary" icon={Plus} onClick={start}>Start a conversation</Button>}>
          <p>Ask a question about your documents. Every conversation is saved here so you can come back to it.</p>
        </EmptyState>
      )}
      {!bothEmpty && !waiting && list && archivedView && archived?.length === 0 && (
        <EmptyState icon={Archive} title="No archived conversations">
          <p>Conversations you archive appear here. You can restore them at any time.</p>
        </EmptyState>
      )}
      {!bothEmpty && !waiting && !archivedView && list?.length === 0 && (
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
