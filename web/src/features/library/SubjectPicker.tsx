import { useCallback, useEffect, useRef, useState } from "react";

import { loadSubjectSuggestions, saveSubjects, type DocumentResponse, type SubjectSuggestions, type Suggestion } from "../../api/documents";
import { Banner } from "../../components/Banner/Banner";
import { Button } from "../../components/Button/Button";
import { Dialog } from "../../components/Dialog/Dialog";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import styles from "./SubjectPicker.module.css";

const MAX_SUBJECTS = 3;
const ORIGIN_LABEL: Record<Suggestion["origin"], string> = { shared: "Shared subject", yours: "Your subject", new: "New" };

type Choice = { subject_ids: string[]; new_names: string[] };

type Props = {
  document: DocumentResponse;
  load?: (documentId: string) => Promise<SubjectSuggestions>;
  save?: (documentId: string, choice: Choice) => Promise<DocumentResponse>;
  onClose: () => void;
  onSaved: (document: DocumentResponse) => void;
};

const defaultLoad = (id: string) => loadSubjectSuggestions(id);
const defaultSave = (id: string, choice: Choice) => saveSubjects(id, choice);

// The learner picks 1-3 of three ranked suggestions for a document (PRD §8 US-4). The first is pre-selected.
export function SubjectPicker({ document, load = defaultLoad, save = defaultSave, onClose, onSaved }: Props) {
  const [loaded, setLoaded] = useState<SubjectSuggestions | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set([0]));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedDoc, setSavedDoc] = useState<DocumentResponse | null>(null);
  const loadRef = useRef(load);
  const alive = useRef(true);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const fetchSuggestions = useCallback(async () => {
    setLoadFailed(false);
    try {
      const result = await loadRef.current(document.document_id);
      if (alive.current) setLoaded(result);
    } catch {
      // A 401 is handled by the API client: the session screen replaces this page.
      if (alive.current) setLoadFailed(true);
    }
  }, [document.document_id]);
  useEffect(() => {
    void fetchSuggestions();
  }, [fetchSuggestions]);

  const suggestions = loaded?.suggestions ?? [];
  const chosen = suggestions.filter((_, i) => selected.has(i));
  const atMax = selected.size >= MAX_SUBJECTS;

  function toggle(index: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(index)) next.add(index);
      return next;
    });
  }

  async function onSave() {
    setSaving(true);
    setSaveError(null);
    const choice: Choice = {
      subject_ids: chosen.flatMap((s) => (s.subject_id ? [s.subject_id] : [])),
      new_names: chosen.filter((s) => s.origin === "new").map((s) => s.name),
    };
    try {
      const updated = await save(document.document_id, choice);
      if (!alive.current) return;
      setSavedDoc(updated);
      onSaved(updated);
    } catch (error) {
      if (!alive.current) return;
      setSaveError(error instanceof Error ? error.message : "");
    }
    setSaving(false);
  }

  const kicker = document.state === "ready" ? "Ready document" : "Processing finished";

  if (savedDoc) {
    return (
      <Dialog
        key="saved" // a fresh dialog, so focus moves to Done
        title="Choose subjects"
        kicker={kicker}
        wide
        onClose={onClose}
        footer={
          <Button variant="primary" data-autofocus onClick={onClose}>
            Done
          </Button>
        }
      >
        <div role="status">
          <Banner variant="success" title="Subjects saved.">
            <em>{document.title}</em> is ready to use.
          </Banner>
        </div>
        <div className={styles.chips}>
          {chosen.map((s) => (
            <SubjectChip key={s.subject_id ?? s.name} name={s.name} hueKey={s.subject_id ?? s.name} />
          ))}
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog
      title="Choose subjects"
      kicker={kicker}
      wide
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!loaded || saving || selected.size === 0} aria-describedby={selected.size === 0 ? "picker-save-hint" : undefined} onClick={() => void onSave()}>
            Save
          </Button>
          <span id="picker-save-hint" className="visually-hidden">
            Choose at least one subject to save.
          </span>
        </>
      }
    >
      <div className={styles.doc}>
        <p className={styles.title}>{document.title}</p>
        {loaded?.summary && <p className={styles.summary}>{loaded.summary}</p>}
      </div>
      {!loaded && !loadFailed && <p className={styles.note}>Loading suggestions…</p>}
      {loadFailed && (
        <div className={styles.note}>
          <p className={styles.error}>Couldn't load suggestions. Try again.</p>
          <Button size="sm" onClick={() => void fetchSuggestions()}>
            Retry
          </Button>
        </div>
      )}
      {loaded && (
        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>Suggested subjects</legend>
          <span className={atMax ? `${styles.counter} ${styles.max}` : styles.counter} aria-live="polite">
            {selected.size} of {MAX_SUBJECTS} selected{atMax ? " · the maximum" : ""}
          </span>
          <div className={styles.chips}>
            {suggestions.map((s, i) => (
              <SubjectChip
                key={s.subject_id ?? s.name}
                name={s.name}
                hueKey={s.subject_id ?? s.name}
                size="lg"
                origin={ORIGIN_LABEL[s.origin]}
                pressed={selected.has(i)}
                disabled={atMax && !selected.has(i)}
                onToggle={() => toggle(i)}
              />
            ))}
          </div>
          {atMax && <p className={styles.helper}>You've chosen 3 subjects, the maximum. Remove one to add another.</p>}
        </fieldset>
      )}
      {saveError !== null && (
        <p className={styles.error} role="alert">
          Couldn't save subjects. Try again.
          {saveError && ` ${saveError}`}
        </p>
      )}
    </Dialog>
  );
}
