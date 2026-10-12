import { CircleAlert, Pencil } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { SessionExpiredError } from "../../auth/authClient";
import styles from "./ThreadTitle.module.css";

const MAX_TITLE = 120;
const EMPTY = "Enter a title";
const SAVE_FAILED = "The title couldn't be saved. Try again.";

type Props = {
  title: string;
  /** Off while there is no conversation to rename yet, or while it is archived: the title is plain text. */
  editable: boolean;
  /** Saves the trimmed title; rejects with the learner's message when the server refuses it. */
  onRename: (title: string) => Promise<void>;
};

/**
 * The chat header's title (DESIGN.md → Chat, PRD US-13): click it, or the pencil shown on hover and focus, to edit it
 * inline. Enter or blur saves, Esc cancels, 1–120 characters; "Enter a title" shows under an empty field.
 */
export function ThreadTitle({ title, editable, onRename }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [refusal, setRefusal] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  // Set while a save is in flight, so the blur that follows Enter (or a second Enter) doesn't save again.
  const saving = useRef(false);
  // Cleared as the field closes: some browsers fire blur when they remove the focused field, which must not save again.
  const open = useRef(false);
  // Where focus goes once the field closes: back to the title after Enter or Esc, nowhere after a click away.
  const refocus = useRef(false);
  const inputId = useId();
  const errorId = useId();

  useEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    } else if (refocus.current) {
      refocus.current = false;
      button.current?.focus();
    }
  }, [editing]);

  const trimmed = draft.trim();
  const message = trimmed ? refusal : EMPTY;

  function start() {
    setDraft(title);
    setRefusal(null);
    open.current = true;
    setEditing(true);
  }

  function close(keepFocus: boolean) {
    open.current = false;
    refocus.current = keepFocus;
    setEditing(false);
  }

  async function save(keepFocus: boolean) {
    if (saving.current || !trimmed) return;
    if (trimmed === title) return close(keepFocus);
    saving.current = true;
    try {
      await onRename(trimmed);
      close(keepFocus);
    } catch (error) {
      // An ended session is reported by the API client; the session screen takes over.
      if (error instanceof SessionExpiredError) return;
      setRefusal(error instanceof Error && error.message ? error.message : SAVE_FAILED);
    } finally {
      saving.current = false;
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      void save(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    }
  }

  // Clicking away saves; with an empty field there is nothing to save, so it cancels.
  function onBlur() {
    if (saving.current || !open.current) return;
    if (trimmed) void save(false);
    else close(false);
  }

  if (editing) {
    return (
      <>
        <div className={styles.edit}>
          <label htmlFor={inputId} className="visually-hidden">
            Conversation title
          </label>
          <input
            ref={input}
            id={inputId}
            className={styles.input}
            type="text"
            maxLength={MAX_TITLE}
            value={draft}
            aria-invalid={message ? true : undefined}
            aria-describedby={message ? errorId : undefined}
            aria-keyshortcuts="Enter Escape"
            onChange={(e) => {
              setDraft(e.target.value);
              setRefusal(null);
            }}
            onKeyDown={onKeyDown}
            onBlur={onBlur}
          />
          {message && (
            <p id={errorId} className={styles.error} role="alert">
              <CircleAlert className={styles.errorIcon} strokeWidth={1.5} aria-hidden="true" />
              {message}
            </p>
          )}
        </div>
        <span className={styles.hint} aria-hidden="true">
          Enter to save · Esc to cancel
        </span>
      </>
    );
  }

  // One line; a long title is cut with an ellipsis, and the full text is in the tooltip and the accessible name.
  if (!editable) {
    return (
      <h1 className={`${styles.heading} ${styles.text}`} title={title}>
        {title}
      </h1>
    );
  }

  return (
    <h1 className={styles.heading}>
      <button ref={button} type="button" className={styles.button} title={title} aria-label={`${title}. Edit title`} onClick={start}>
        <span className={styles.text}>{title}</span>
        <Pencil className={styles.pen} strokeWidth={1.5} aria-hidden="true" />
      </button>
    </h1>
  );
}
