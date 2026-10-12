import { Archive, ArchiveRestore, MessageSquare } from "lucide-react";
import { Link, useNavigate } from "react-router";

import type { ThreadSummaryResponse } from "../../api/conversations";
import { conversationTitle } from "../../app/conversations";
import { RowMenu } from "../../components/RowMenu/RowMenu";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import styles from "./ConversationTable.module.css";
import { lastActivity } from "./lastActivity";

const SHOWN_SUBJECTS = 2;

type Props = {
  conversations: ThreadSummaryResponse[];
  archived: boolean;
  onArchive: (thread: ThreadSummaryResponse) => void;
  onRestore: (thread: ThreadSummaryResponse) => void;
  busy?: ReadonlySet<string>; // thread ids with a change in flight
};

// The learner's conversations, newest first as the API sends them. The title is the link; the whole row is clickable.
export function ConversationTable({ conversations, archived, onArchive, onRestore, busy }: Props) {
  const navigate = useNavigate();
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col">Conversation</th>
          <th scope="col" className={styles.colSubjects}>Subjects of documents used</th>
          <th scope="col" className={styles.colDocuments}>Documents</th>
          <th scope="col" className={`${styles.colActivity} ${styles.right}`}>Last activity</th>
          <th scope="col" className={styles.colActions}><span className="visually-hidden">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {conversations.map((t) => {
          const path = `/chat/${t.thread_id}`;
          const title = conversationTitle(t);
          const rest = t.subjects.slice(SHOWN_SUBJECTS).map((s) => s.name).join(", ");
          const hidden = t.subjects.length - SHOWN_SUBJECTS;
          return (
            <tr
              key={t.thread_id}
              className={styles.row}
              onClick={(event) => {
                if (!(event.target as HTMLElement).closest("a, button, [role='menu']")) navigate(path); // links and the menu act for themselves
              }}
            >
              <td>
                <Link to={path} className={styles.title} title={title}>{title}</Link>
              </td>
              <td>
                {t.subjects.length ? (
                  <div className={styles.subjects}>
                    {t.subjects.slice(0, SHOWN_SUBJECTS).map((s) => <SubjectChip key={s.subject_id} name={s.name} hueKey={s.subject_id} size="sm" truncate />)}
                    {hidden > 0 && <span className={styles.more} title={rest}>
                        <span aria-hidden="true">+{hidden}</span>
                        <span className="visually-hidden">{hidden} more: {rest}</span>
                      </span>}
                  </div>
                ) : (
                  <span className={styles.muted}>None yet</span>
                )}
              </td>
              <td className={styles.number}>{t.documents}</td>
              <td className={`${styles.date} ${styles.right}`}>
                <time dateTime={t.last_activity}>{lastActivity(t.last_activity)}</time>
              </td>
              <td className={styles.actions}>
                <RowMenu
                  label={`Actions for ${title}`}
                  disabled={busy?.has(t.thread_id)}
                  items={[
                    { label: "Open", icon: MessageSquare, onSelect: () => navigate(path) },
                    archived
                      ? { label: "Restore", icon: ArchiveRestore, onSelect: () => onRestore(t) }
                      : { label: "Archive", icon: Archive, onSelect: () => onArchive(t) },
                  ]}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
