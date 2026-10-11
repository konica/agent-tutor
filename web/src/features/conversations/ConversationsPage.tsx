import { MessageSquare, Plus } from "lucide-react";
import { useNavigate } from "react-router";

import { useConversations } from "../../app/conversations";
import { NAV } from "../../app/nav";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { ConversationTable } from "./ConversationTable";
import styles from "./ConversationsPage.module.css";

// The learner's active conversations (PRD US-13). The app shell loads the list and reloads it on every navigation.
export function ConversationsPage() {
  const { list, failed } = useConversations();
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
      {list && list.length > 0 && <ConversationTable conversations={list} />}
    </>
  );
}
