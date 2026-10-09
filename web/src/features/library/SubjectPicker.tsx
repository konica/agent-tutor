import { CircleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";

import { loadSubjectSuggestions, saveSubjects, type DocumentResponse, type SubjectSuggestions, type Suggestion } from "../../api/documents";
import { searchCatalog, type SubjectMatch } from "../../api/subjects";
import { Banner } from "../../components/Banner/Banner";
import { Button } from "../../components/Button/Button";
import { Dialog } from "../../components/Dialog/Dialog";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import styles from "./SubjectPicker.module.css";

const MAX_SUBJECTS = 3;
const MAX_NAME = 60; // the server's limit for a typed subject name
const SEARCH_DELAY_MS = 200;
const ORIGIN_LABEL: Record<Suggestion["origin"], string> = { shared: "Shared subject", yours: "Your subject", new: "New" };

type Choice = { subject_ids: string[]; new_names: string[] };

type Props = {
  document: DocumentResponse;
  load?: (documentId: string) => Promise<SubjectSuggestions>;
  save?: (documentId: string, choice: Choice) => Promise<DocumentResponse>;
  search?: (query: string) => Promise<SubjectMatch[]>;
  onClose: () => void;
  onSaved: (document: DocumentResponse) => void;
  step?: { index: number; total: number }; // 0-based place in a step-through of waiting documents
  onSkip?: () => void;
};

const defaultLoad = (id: string) => loadSubjectSuggestions(id);
const defaultSave = (id: string, choice: Choice) => saveSubjects(id, choice);
const defaultSearch = (query: string) => searchCatalog(query);

// Mirrors the server's name key (NFKC, casefold, single spaces) closely enough to avoid duplicate chips;
// the server is authoritative and reuses an existing subject for an equal name.
const normalize = (s: string) => s.normalize("NFKC").toLowerCase().trim().replace(/\s+/g, " ");

type Option = { kind: "match"; match: SubjectMatch } | { kind: "create" };

// The learner picks 1-3 subjects for a document (PRD §8 US-2b): from three ranked suggestions (the first is
// pre-selected) or by typing a name, with type-ahead over the shared catalog. Typed chips follow the suggestions.
export function SubjectPicker({ document, load = defaultLoad, save = defaultSave, search = defaultSearch, onClose, onSaved, step, onSkip }: Props) {
  const [loaded, setLoaded] = useState<SubjectSuggestions | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set([0]));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedDoc, setSavedDoc] = useState<DocumentResponse | null>(null);
  const [added, setAdded] = useState<Suggestion[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SubjectMatch[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const loadRef = useRef(load);
  const searchRef = useRef(search);
  const requestRef = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);
  useEffect(() => {
    searchRef.current = search;
  }, [search]);
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
  const chips = [...suggestions, ...added]; // indices in `selected` refer to this list
  const chosen = chips.filter((_, i) => selected.has(i));
  const atMax = selected.size >= MAX_SUBJECTS;

  const typed = query.trim().replace(/\s+/g, " ");
  const tooLong = typed.length > MAX_NAME;
  const searchable = typed !== "" && !tooLong && !atMax;
  const exact = results.find((r) => normalize(r.name) === normalize(typed));
  const options: Option[] = [...results.map((match): Option => ({ kind: "match", match })), ...(exact ? [] : [{ kind: "create" } as const])];
  const listShown = open && searchable && options.length > 0;

  // Text still in the field is part of Save: it resolves like Add, and an equal chip is not sent twice.
  const typedChoice: Suggestion | null =
    typed && !tooLong ? (exact ? { subject_id: exact.subject_id, name: exact.name, origin: exact.origin } : { subject_id: null, name: typed, origin: "new" }) : null;
  const typedIndex = typedChoice ? chipIndexOf(typedChoice) : -1;
  const typedAdds = typedChoice !== null && !selected.has(typedIndex);
  const toSave = typedAdds ? [...chosen, typedIndex >= 0 ? chips[typedIndex]! : typedChoice] : chosen;
  const overMax = toSave.length > MAX_SUBJECTS;

  function chipIndexOf(item: Suggestion) {
    const key = normalize(item.name);
    return chips.findIndex((c) => (item.subject_id !== null && c.subject_id === item.subject_id) || normalize(c.name) === key);
  }

  // Type-ahead is optional: a failed search shows no matches, and Add still works.
  useEffect(() => {
    const request = ++requestRef.current;
    if (!searchable) {
      setResults([]);
      setOpen(false);
      return;
    }
    const timer = setTimeout(() => {
      const apply = (found: SubjectMatch[]) => {
        if (!alive.current || request !== requestRef.current) return; // a newer query is on its way
        setResults(found);
        setActive(-1);
        const input = inputRef.current;
        if (input && input === input.ownerDocument.activeElement) setOpen(true); // not after the learner left the field
      };
      searchRef.current(typed).then(apply, () => apply([]));
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [typed, searchable]);

  // Selects an equal chip (same subject, or the same name) rather than adding a duplicate.
  function addChoice(item: Suggestion) {
    const existing = chipIndexOf(item);
    const index = existing >= 0 ? existing : chips.length;
    if (existing < 0) setAdded((current) => [...current, item]);
    setSelected((current) => new Set(current).add(index));
    setQuery("");
    setResults([]);
    setOpen(false);
    setActive(-1);
    inputRef.current?.focus();
  }

  function addTyped() {
    if (!typed || tooLong || atMax) return;
    if (exact) addChoice({ subject_id: exact.subject_id, name: exact.name, origin: exact.origin });
    else addChoice({ subject_id: null, name: typed, origin: "new" });
  }

  function pick(option: Option) {
    if (option.kind === "match") addChoice({ subject_id: option.match.subject_id, name: option.match.name, origin: option.match.origin });
    else addTyped();
  }

  function onInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!searchable || options.length === 0) return;
      event.preventDefault();
      const last = options.length - 1;
      if (!listShown) {
        setOpen(true);
        setActive(event.key === "ArrowDown" ? 0 : last);
      } else if (event.key === "ArrowDown") setActive((i) => Math.min(i + 1, last));
      else setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = listShown && active >= 0 ? options[active] : undefined;
      if (option) pick(option);
      else addTyped();
    } else if (event.key === "Escape" && listShown) {
      event.stopPropagation(); // the dialog closes on an Escape that reaches its panel
      setOpen(false);
      setActive(-1);
    }
  }

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
      subject_ids: toSave.flatMap((s) => (s.subject_id ? [s.subject_id] : [])),
      new_names: toSave.filter((s) => s.origin === "new").map((s) => s.name),
    };
    try {
      const updated = await save(document.document_id, choice);
      if (!alive.current) return;
      if (step) {
        onSaved(updated); // the parent moves on to the next document or closes, so no saved screen
        return;
      }
      setSavedDoc(updated);
      onSaved(updated);
    } catch (error) {
      if (!alive.current) return;
      setSaveError(error instanceof Error ? error.message : "");
    }
    setSaving(false);
  }

  const last = !step || step.index === step.total - 1;
  const kicker = step ? `Document ${step.index + 1} of ${step.total}` : document.state === "ready" ? "Ready document" : "Processing finished";

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
          {savedDoc.subjects.map((s) => (
            <SubjectChip key={s.subject_id} name={s.name} hueKey={s.subject_id} />
          ))}
        </div>
      </Dialog>
    );
  }

  const saveDescribedBy = [toSave.length === 0 && "picker-save-hint", tooLong && "picker-add-error", overMax && "picker-max-help"].filter(Boolean).join(" ");

  return (
    <Dialog
      title="Choose subjects"
      kicker={kicker}
      wide
      onClose={onClose}
      footer={
        <>
          {step ? (
            <>
              <span className={styles.step}>
                {step.index + 1} of {step.total}
              </span>
              <Button variant="quiet" onClick={onSkip}>
                Skip
              </Button>
            </>
          ) : (
            <Button onClick={onClose}>Cancel</Button>
          )}
          <Button
            variant="primary"
            disabled={!loaded || saving || toSave.length === 0 || tooLong || overMax}
            aria-describedby={saveDescribedBy || undefined}
            onClick={() => void onSave()}
          >
            {last ? "Save" : "Save and next"}
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
            {chips.map((s, i) => (
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
          {atMax && <p id="picker-max-help" className={styles.helper}>You've chosen 3 subjects, the maximum. Remove one to add another.</p>}
        </fieldset>
      )}
      {loaded && (
        <div className={styles.add}>
          <label htmlFor="picker-add" className={styles.addLabel}>
            Add your own
          </label>
          <div className={styles.addRow}>
            <div className={styles.combo}>
              <input
                ref={inputRef}
                id="picker-add"
                className={tooLong ? `${styles.input} ${styles.invalid}` : styles.input}
                type="text"
                autoComplete="off"
                spellCheck={false}
                role="combobox"
                aria-expanded={listShown}
                aria-controls="picker-results"
                aria-autocomplete="list"
                aria-activedescendant={listShown && active >= 0 ? `picker-option-${active}` : undefined}
                aria-invalid={tooLong || undefined}
                aria-describedby={tooLong ? "picker-add-hint picker-add-error" : "picker-add-hint"}
                value={query}
                disabled={atMax}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActive(-1); // the highlighted option belongs to the old text; Enter now adds the typed name
                }}
                onKeyDown={onInputKeyDown}
                onBlur={() => setOpen(false)}
              />
              <ul id="picker-results" role="listbox" aria-label="Matching subjects" className={styles.list} hidden={!listShown}>
                {listShown &&
                  options.map((option, i) => (
                    <li
                      key={option.kind === "match" ? option.match.subject_id : "create"}
                      id={`picker-option-${i}`}
                      role="option"
                      aria-selected={i === active}
                      className={i === active ? `${styles.option} ${styles.active}` : styles.option}
                      onMouseDown={(event) => event.preventDefault()} // keep focus in the input
                      onMouseEnter={() => setActive(i)}
                      onClick={() => pick(option)}
                    >
                      <span className={styles.optionName}>{option.kind === "match" ? option.match.name : `Create "${typed}"`}</span>
                      <span className={styles.meta}>{option.kind === "match" ? ORIGIN_LABEL[option.match.origin] : "New subject, visible to everyone"}</span>
                    </li>
                  ))}
              </ul>
            </div>
            <Button disabled={atMax || !typed || tooLong} onClick={addTyped}>
              Add
            </Button>
          </div>
          <div className={styles.addNotes}>
            <span id="picker-add-hint">Subject names are visible to everyone. Don't include personal information.</span>
            <span className={tooLong ? `${styles.length} ${styles.over}` : styles.length}>
              {typed.length}/{MAX_NAME}
            </span>
          </div>
          {tooLong && (
            <p id="picker-add-error" className={styles.addError}>
              <CircleAlert className={styles.errorIcon} strokeWidth={1.5} aria-hidden="true" />
              Subject names can be up to 60 characters.
            </p>
          )}
        </div>
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
