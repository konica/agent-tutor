import { Filter, MessageSquare, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { hasConversationFilters, listConversations, type ConversationFilters as Filters, type ThreadSummaryResponse } from "../../api/conversations";
import type { SubjectResponse } from "../../api/generated/types.gen";
import { loadMySubjects } from "../../api/subjects";
import { useConversations } from "../../app/conversations";
import { NAV } from "../../app/nav";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { ConversationFilters } from "./ConversationFilters";
import { ConversationTable } from "./ConversationTable";
import styles from "./ConversationsPage.module.css";
import { useFilteredConversations } from "./useFilteredConversations";

type Props = { loadConversations?: (filters: Filters) => Promise<ThreadSummaryResponse[]>; loadSubjects?: () => Promise<SubjectResponse[]> };

const defaultLoadSubjects = () => loadMySubjects();

// The learner's active conversations (PRD US-13). The app shell loads the full list and reloads it on every navigation;
// while filters are set this page loads the matching ones itself, so the side nav keeps the most recent unfiltered.
export function ConversationsPage({ loadConversations = listConversations, loadSubjects = defaultLoadSubjects }: Props = {}) {
  const { list, failed } = useConversations();
  const [filters, setFilters] = useState<Filters>({});
  const [subjects, setSubjects] = useState<SubjectResponse[]>([]);
  useEffect(() => {
    let alive = true;
    loadSubjects().then((s) => alive && setSubjects(s), () => {}); // the Subject filter just stays empty
    return () => {
      alive = false;
    };
  }, [loadSubjects]);
  const filtering = hasConversationFilters(filters);
  const filtered = useFilteredConversations(loadConversations, filters, list);
  const rows = filtering ? filtered.list : list;
  const clear = () => setFilters({});
  const navigate = useNavigate();
  const start = () => navigate("/chat");
  const description = NAV.find((item) => item.path === "/conversations")?.description;
  return (
    <>
      <PageHeader
        title="Conversations"
        count={list ? `${list.length} ${list.length === 1 ? "conversation" : "conversations"}` : undefined}
        description={description}
        actions={<Button variant="primary" icon={Plus} onClick={start}>New conversation</Button>}
      />
      {failed && list === null && <p className={styles.error}>Can't load your conversations. Reload the page to try again.</p>}
      {list?.length === 0 && (
        <EmptyState icon={MessageSquare} title="No conversations yet" actions={<Button variant="primary" icon={Plus} onClick={start}>Start a conversation</Button>}>
          <p>Ask a question about your documents. Every conversation is saved here so you can come back to it.</p>
        </EmptyState>
      )}
      {list && list.length > 0 && (
        <div className={styles.toolbar}>
          <ConversationFilters filters={filters} onChange={setFilters} subjects={subjects} count={rows ? rows.length : null} onClear={clear} />
        </div>
      )}
      {filtering && filtered.failed && <p className={styles.error}>Can't load your conversations. Reload the page to try again.</p>}
      {rows && rows.length === 0 && filtering && (
        <EmptyState icon={Filter} title="No conversations match these filters" actions={<Button onClick={clear}>Clear filters</Button>}>
          <p>Try another subject, a wider date range or another search.</p>
        </EmptyState>
      )}
      {rows && rows.length > 0 && <ConversationTable conversations={rows} />}
    </>
  );
}
