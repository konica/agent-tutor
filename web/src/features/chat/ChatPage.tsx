import { ArrowUp, CircleAlert, Clock, FileText, Upload } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import {
  askInNewThread,
  AskRefusedError,
  formatCitation,
  NoDocumentsError,
  type ChatCitation,
  type ChatEvent,
} from "../../api/chat";
import { loadDocuments } from "../../api/documents";
import type { DocumentResponse } from "../../api/generated/types.gen";
import { SessionExpiredError, sessionExpiry } from "../../auth/authClient";
import { IconButton } from "../../components/Button/IconButton";
import { LinkButton } from "../../components/Button/LinkButton";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import styles from "./ChatPage.module.css";

type Props = {
  ask?: (question: string) => AsyncIterable<ChatEvent>;
  loadDocs?: () => Promise<DocumentResponse[]>;
};

type Exchange = {
  question: string;
  answer: string;
  citations: ChatCitation[];
};

// "ended" is a session that expired while loading: the session screen takes over, this page shows nothing.
type Library = { status: "loading" | "failed" | "ended" } | { status: "ready" };

type Problem = { message: string };

const MAX_QUESTION = 4000;
const GENERIC_FAILURE = "The tutor couldn't answer right now. Try again in a moment.";

const defaultAsk = (question: string) => askInNewThread(question);
const defaultLoadDocs = () => loadDocuments();

function processingHint(count: number) {
  return count === 1
    ? "1 document is still processing and can't be used yet."
    : `${count} documents are still processing and can't be used yet.`;
}

// Single turn (#82): each question starts a new thread and replaces the previous exchange.
export function ChatPage({ ask = defaultAsk, loadDocs = defaultLoadDocs }: Props) {
  const [question, setQuestion] = useState("");
  const [answering, setAnswering] = useState(false);
  const [exchange, setExchange] = useState<Exchange | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [library, setLibrary] = useState<Library>({ status: "loading" });
  const [processing, setProcessing] = useState(0);
  const [noDocuments, setNoDocuments] = useState(false);
  const alive = useRef(true);
  const busy = useRef(false);
  const sourcesId = useId();

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // The documents decide what the page is: none ready → upload first; still processing → a hint.
  useEffect(() => {
    let current = true;
    loadDocs().then(
      (docs) => {
        if (!current) return;
        setProcessing(docs.filter((d) => d.state === "processing").length);
        if (docs.some((d) => d.state === "ready")) setLibrary({ status: "ready" });
        else setNoDocuments(true);
      },
      (error: unknown) => current && setLibrary({ status: error instanceof SessionExpiredError ? "ended" : "failed" }),
    );
    return () => {
      current = false;
    };
  }, [loadDocs]);

  const trimmed = question.trim();
  const canAsk = !answering && trimmed.length > 0;

  async function submit() {
    // The ref also stops a second Enter that lands before the disabled state renders.
    if (!canAsk || busy.current) return;
    busy.current = true;
    setAnswering(true);
    setProblem(null);
    setExchange({ question: trimmed, answer: "", citations: [] });
    setQuestion("");
    // The protocol always ends with done or error; a stream that just stops (dropped connection) failed.
    let ended = false;
    try {
      for await (const event of ask(trimmed)) {
        if (!alive.current) break; // leaving the page stops reading, which closes the stream
        if (event.type === "done" || event.type === "error") ended = true;
        if (event.type === "delta") setExchange((e) => e && { ...e, answer: e.answer + event.text });
        else if (event.type === "citations") setExchange((e) => e && { ...e, citations: event.citations });
        else if (event.type === "error") {
          // The token stopped working mid-answer: the session screen asks the learner to sign in again.
          if (event.code === "unauthenticated") sessionExpiry.notify();
          else setProblem({ message: event.message });
        }
      }
      // Any partial answer stays visible above the message.
      if (alive.current && !ended) setProblem({ message: GENERIC_FAILURE });
    } catch (error) {
      if (!alive.current) return;
      // The last ready document was archived since the page loaded.
      if (error instanceof NoDocumentsError) setNoDocuments(true);
      else if (error instanceof AskRefusedError) setProblem({ message: error.message });
      // A SessionExpiredError was already reported by the API client; the session screen replaces this page.
      else if (!(error instanceof SessionExpiredError)) setProblem({ message: GENERIC_FAILURE });
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

  if (noDocuments) {
    return (
      <div className={styles.column}>
        <EmptyState
          icon={Upload}
          title="Upload a document first"
          actions={
            <LinkButton to="/library" variant="primary" icon={Upload}>
              Upload
            </LinkButton>
          }
        >
          The tutor answers only from your documents. Add a PDF to your Library and you can start asking in a few minutes.
        </EmptyState>
      </div>
    );
  }

  if (library.status === "ended") return null;

  if (library.status !== "ready") {
    return (
      <div className={styles.column}>
        <PageHeader title="New conversation" />
        {library.status === "failed" && (
          <p className={styles.problem}>
            <CircleAlert className={styles.problemIcon} strokeWidth={1.5} aria-hidden="true" />
            Your documents couldn't be loaded. Reload the page to try again.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={styles.column}>
      <div className={styles.head}>
        <PageHeader title={exchange ? exchange.question : "New conversation"} />
      </div>
      {!exchange && (
        <section className={styles.welcome}>
          <h2 className={styles.welcomeTitle}>Ask about your documents</h2>
          <p className={styles.welcomeText}>
            I answer only from the documents in your Library and show the page each answer came from. There's nothing to
            choose first: just ask.
          </p>
        </section>
      )}

      {exchange && (
        <p className={styles.question}>
          <span className="visually-hidden">You asked: </span>
          {exchange.question}
        </p>
      )}

      {/* Announced once when the answer is complete, never word by word (DESIGN.md → Accessibility). */}
      <div className={styles.answerRegion} aria-live="polite" aria-busy={answering}>
        {exchange && exchange.answer && <p className={styles.answer}>{exchange.answer}</p>}
        {exchange && exchange.citations.length > 0 && (
          <div className={styles.sources}>
            <span className={styles.sourcesLabel} id={sourcesId}>
              Sources
            </span>
            {/* Each source shows the [n] the answer's text uses for it; an answer may cite [2] without [1]. */}
            <ul className={styles.sourceList} aria-labelledby={sourcesId}>
              {exchange.citations.map((c) => (
                <li key={c.chunk_id}>
                  <span className={styles.source} title={formatCitation(c)}>
                    <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
                    <span className={styles.sourceMarker}>[{c.n}]</span>{" "}
                    <span className={styles.sourceTitle}>{c.document_title}</span>{" "}
                    <span>· {c.page === null ? "page unavailable" : `p. ${c.page}`}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {problem && (
          <p className={styles.problem}>
            <CircleAlert className={styles.problemIcon} strokeWidth={1.5} aria-hidden="true" />
            {problem.message}
          </p>
        )}
      </div>

      {answering && <p className={styles.thinking}>The tutor is answering…</p>}

      <form className={styles.form} onSubmit={onSubmit}>
        <label htmlFor="chat-question" className="visually-hidden">
          Your question
        </label>
        <div className={styles.composer}>
          <textarea
            id="chat-question"
            className={styles.input}
            rows={1}
            maxLength={MAX_QUESTION}
            placeholder="Ask about your documents"
            value={question}
            disabled={answering}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <IconButton type="submit" label="Ask" icon={ArrowUp} tip={false} disabled={!canAsk} className={styles.send} />
        </div>
        <div className={styles.statusLine}>
          <span className={styles.hint}>
            {processing > 0 && (
              <>
                <Clock className={styles.hintIcon} strokeWidth={1.5} aria-hidden="true" />
                {processingHint(processing)}
              </>
            )}
          </span>
          <span>Enter to send · Shift + Enter for a new line</span>
        </div>
      </form>
    </div>
  );
}
