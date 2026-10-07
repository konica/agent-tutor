import { Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router";

import {
  askInNewThread,
  AskRefusedError,
  formatCitation,
  NoDocumentsError,
  type ChatCitation,
  type ChatEvent,
} from "../../api/chat";
import { SessionExpiredError, sessionExpiry } from "../../auth/authClient";
import { Button } from "../../components/Button/Button";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import styles from "./ChatPage.module.css";

type Props = { ask?: (question: string) => AsyncIterable<ChatEvent> };

type Exchange = {
  question: string;
  subjects: { subject_id: string; name: string }[];
  answer: string;
  citations: ChatCitation[];
};

type Problem = { kind: "no-documents"; message: string } | { kind: "message"; message: string };

const MAX_QUESTION = 4000;
const GENERIC_FAILURE = "The tutor couldn't answer right now. Try again in a moment.";

const defaultAsk = (question: string) => askInNewThread(question);

// Single turn (#82): each question starts a new thread and replaces the previous exchange.
export function ChatPage({ ask = defaultAsk }: Props) {
  const [question, setQuestion] = useState("");
  const [answering, setAnswering] = useState(false);
  const [exchange, setExchange] = useState<Exchange | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const alive = useRef(true);
  const busy = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const trimmed = question.trim();
  const canAsk = !answering && trimmed.length > 0;

  async function submit() {
    // The ref also stops a second Enter that lands before the disabled state renders.
    if (!canAsk || busy.current) return;
    busy.current = true;
    setAnswering(true);
    setProblem(null);
    setExchange({ question: trimmed, subjects: [], answer: "", citations: [] });
    setQuestion("");
    // The protocol always ends with done or error; a stream that just stops (dropped connection) failed.
    let ended = false;
    try {
      for await (const event of ask(trimmed)) {
        if (!alive.current) break; // leaving the page stops reading, which closes the stream
        if (event.type === "done" || event.type === "error") ended = true;
        if (event.type === "thread") setExchange((e) => e && { ...e, subjects: event.subjects });
        else if (event.type === "delta") setExchange((e) => e && { ...e, answer: e.answer + event.text });
        else if (event.type === "citations") setExchange((e) => e && { ...e, citations: event.citations });
        else if (event.type === "error") {
          // The token stopped working mid-answer: the session screen asks the learner to sign in again.
          if (event.code === "unauthenticated") sessionExpiry.notify();
          else setProblem({ kind: "message", message: event.message });
        }
      }
      // Any partial answer stays visible above the message.
      if (alive.current && !ended) setProblem({ kind: "message", message: GENERIC_FAILURE });
    } catch (error) {
      if (!alive.current) return;
      if (error instanceof NoDocumentsError) setProblem({ kind: "no-documents", message: error.message });
      else if (error instanceof AskRefusedError) setProblem({ kind: "message", message: error.message });
      // A SessionExpiredError was already reported by the API client; the session screen replaces this page.
      else if (!(error instanceof SessionExpiredError)) setProblem({ kind: "message", message: GENERIC_FAILURE });
    } finally {
      busy.current = false;
      if (alive.current) setAnswering(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  // Enter asks; Shift+Enter adds a line.
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <div className={styles.column}>
      <PageHeader title="Chat" description="Ask a question about your documents." />

      {exchange && (
        <div className={styles.exchange}>
          <p className={styles.question}>
            <span className="visually-hidden">You asked: </span>
            {exchange.question}
          </p>
          {exchange.subjects.length > 0 && (
            <ul className={styles.subjects} aria-label="Subjects">
              {exchange.subjects.map((s) => (
                <li key={s.subject_id} className={styles.subject}>
                  {s.name}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Announced once when the answer is complete, never word by word (DESIGN.md → Accessibility). */}
      <div className={styles.answerRegion} aria-live="polite" aria-busy={answering}>
        {exchange && exchange.answer && <p className={styles.answer}>{exchange.answer}</p>}
        {exchange && exchange.citations.length > 0 && (
          <section className={styles.citations} aria-label="Citations">
            <h2 className={styles.citationsTitle}>Citations</h2>
            {/* Each citation shows the [n] the answer's text uses for it; an answer may cite [2] without [1]. */}
            <ul>
              {exchange.citations.map((c) => (
                <li key={c.chunk_id}>
                  <span className={styles.marker}>[{c.n}]</span> <span>{formatCitation(c)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        {problem?.kind === "no-documents" && (
          <p className={styles.problem}>
            {problem.message}
            {" "}
            <Link to="/library">Go to Library</Link>
          </p>
        )}
        {problem?.kind === "message" && <p className={styles.problem}>{problem.message}</p>}
      </div>

      {answering && <p className={styles.thinking}>The tutor is answering…</p>}

      <form className={styles.form} onSubmit={onSubmit}>
        <label htmlFor="chat-question" className="visually-hidden">
          Your question
        </label>
        <textarea
          id="chat-question"
          className={styles.input}
          rows={3}
          maxLength={MAX_QUESTION}
          placeholder="Ask about your documents"
          value={question}
          disabled={answering}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <Button type="submit" variant="primary" icon={Send} disabled={!canAsk}>
          Ask
        </Button>
      </form>
    </div>
  );
}
