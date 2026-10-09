import { CircleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { Dialog } from "../../components/Dialog/Dialog";
import styles from "./DocumentPicker.module.css";

type Props = {
  /** The documents already on the conversation's list: shown checked and fixed. */
  listedIds: ReadonlySet<string>;
  loadReady: () => Promise<DocumentResponse[]>;
  /** Rejecting keeps the dialog open with an error line; resolving is the parent's cue to close it. */
  onAdd: (ids: string[]) => Promise<void>;
  onClose: () => void;
};

/** The most documents one add request carries; matches the API's limit. */
const MAX_ADD = 50;

function byline(d: DocumentResponse): string {
  return [d.authors.join(", "), d.year === null ? "" : String(d.year)].filter(Boolean).join(" · ");
}

function addLabel(n: number): string {
  if (n === 0) return "Add";
  return n === 1 ? "Add 1 document" : `Add ${n} documents`;
}

// "Add documents" (PRD US-4c): a searchable list of the learner's ready documents; listed ones are checked and fixed.
export function DocumentPicker({ listedIds, loadReady, onAdd, onClose }: Props) {
  const [docs, setDocs] = useState<DocumentResponse[] | "failed" | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    loadReady().then(
      (d) => current && setDocs(d),
      () => current && setDocs("failed"),
    );
    return () => {
      current = false;
    };
  }, [loadReady]);

  const shown = useMemo(() => {
    if (!Array.isArray(docs)) return [];
    const q = query.trim().toLowerCase();
    return q ? docs.filter((d) => d.title.toLowerCase().includes(q)) : docs;
  }, [docs, query]);

  function toggle(id: string, on: boolean) {
    setSelected((s) => (on ? [...s, id] : s.filter((x) => x !== id)));
  }

  async function add() {
    setAdding(true);
    setFailed(false);
    try {
      // In the list's order, not the order they were checked.
      const order = Array.isArray(docs) ? docs.map((d) => d.document_id) : [];
      await onAdd(order.filter((id) => selected.includes(id)));
    } catch {
      setFailed(true);
      setAdding(false);
    }
  }

  const n = selected.length;
  const atLimit = n >= MAX_ADD;
  return (
    <Dialog
      title="Add documents"
      wide
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={n === 0 || adding} onClick={() => void add()}>
            {addLabel(n)}
          </Button>
        </>
      }
    >
      <input
        className={styles.search}
        type="search"
        placeholder="Search your documents"
        aria-label="Search your documents"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        data-autofocus
      />
      {docs === "failed" ? (
        <p className={styles.error}>
          <CircleAlert className={styles.errorIcon} strokeWidth={1.5} aria-hidden="true" />
          Your documents couldn't be loaded.
        </p>
      ) : (
        <ul className={styles.list} aria-label="Your ready documents" aria-busy={docs === null}>
          {docs !== null && shown.length === 0 && <li className={styles.empty}>No ready documents match.</li>}
          {shown.map((d) => {
            const listed = listedIds.has(d.document_id);
            return (
              <li key={d.document_id}>
                <label className={styles.row}>
                  <input
                    type="checkbox"
                    checked={listed || selected.includes(d.document_id)}
                    disabled={listed || (atLimit && !selected.includes(d.document_id))}
                    onChange={(e) => toggle(d.document_id, e.target.checked)}
                  />
                  <span className={styles.title} title={d.title}>
                    {d.title}
                  </span>
                  <span className={styles.meta}>{listed ? "In this conversation" : byline(d)}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {atLimit && <p className={styles.empty}>You can add up to {MAX_ADD} documents at a time.</p>}
      {failed && (
        <p role="alert" className={styles.error}>
          <CircleAlert className={styles.errorIcon} strokeWidth={1.5} aria-hidden="true" />
          Couldn't add the documents. Try again.
        </p>
      )}
    </Dialog>
  );
}
