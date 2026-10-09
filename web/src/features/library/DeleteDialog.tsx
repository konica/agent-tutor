import { Archive, Trash2 } from "lucide-react";

import type { DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { Dialog } from "../../components/Dialog/Dialog";
import styles from "./DeleteDialog.module.css";

type Props = { doc: DocumentResponse; busy?: boolean; error?: string; onCancel: () => void; onDelete: () => void; onArchive: () => void };

// US-10c: Cancel is focused first; Delete is the danger action; an active document can be archived instead.
export function DeleteDialog({ doc, busy = false, error, onCancel, onDelete, onArchive }: Props) {
  return (
    <Dialog
      title={
        <>
          Delete <em>{doc.title}</em>?
        </>
      }
      onClose={onCancel}
      footer={
        <>
          <Button data-autofocus onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" icon={Trash2} disabled={busy} onClick={onDelete}>
            Delete
          </Button>
        </>
      }
    >
      <p className={styles.text}>This can't be undone. Conversations and notes keep their text.</p>
      {!doc.archived && (
        <div className={styles.alternative}>
          <p className={styles.text}>Archive hides it and can be undone.</p>
          <Button size="sm" icon={Archive} disabled={busy} onClick={onArchive}>
            Archive instead
          </Button>
        </div>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
