import { Clock, Send, Upload } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router";

import {
  askInNewThread,
  AskRefusedError,
  chooseSubjects,
  formatCitation,
  loadThread,
  NoDocumentsError,
  QuestionExpiredError,
  type ChatCitation,
  type ChatEvent,
  type ThreadView,
} from "../../api/chat";
import { loadDocuments } from "../../api/documents";
import type { DocumentResponse } from "../../api/generated/types.gen";
import { loadMySubjects } from "../../api/subjects";
import { SessionExpiredError, sessionExpiry } from "../../auth/authClient";
import { Button } from "../../components/Button/Button";
import { LinkButton } from "../../components/Button/LinkButton";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import styles from "./ChatPage.module.css";
import { ChooseSubjects } from "./ChooseSubjects";

type Subject = { subject_id: string; name: string };

type Props = {
  ask?: (question: string) => AsyncIterable<ChatEvent>;
  choose?: (threadId: string, subjectIds: string[]) => AsyncIterable<ChatEvent>;
  loadPending?: (threadId: string) => Promise<ThreadView | null>;
  loadSubjects?: () => Promise<Subject[]>;
  loadDocs?: () => Promise<DocumentResponse[]>;
};

type Exchange = {
  question: string;
  subjects: Subject[];
  answer: string;
  citations: ChatCitation[];
  // Detection was unsure: the question waits for the learner to pick 1-3 of these subjects.
  pending: { threadId: string; subjects: Subject[] } | null;
};

// The waiting thread's id is kept in the URL (?thread=), so the pick survives a reload.
const THREAD_PARAM = "thread";

// "ended" is a session that expired while loading: the session screen takes over, this page shows nothing.
type Subjects = { status: "loading" | "failed" | "ended" } | { status: "ready"; list: Subject[] };

type Problem = { message: string };

const MAX_QUESTION = 4000;
const GENERIC_FAILURE = "The tutor couldn't answer right now. Try again in a moment.";
const RESUME_FAILURE = "Your question couldn't be loaded. Reload the page to try again.";

const defaultAsk = (question: string) => askInNewThread(question);
const defaultChoose = (threadId: string, subjectIds: string[]) => chooseSubjects(threadId, subjectIds);
const defaultLoadPending = (threadId: string) => loadThread(threadId);
const defaultLoadSubjects = () => loadMySubjects();
const defaultLoadDocs = () => loadDocuments();

function processingHint(count: number) {
  return count === 1
    ? "1 document is still processing and can't be used yet."
    : `${count} documents are still processing and can't be used yet.`;
}

// Single turn (#82): each question starts a new thread and replaces the previous exchange.
export function ChatPage({
  ask = defaultAsk,
  choose = defaultChoose,
  loadPending = defaultLoadPending,
  loadSubjects = defaultLoadSubjects,
  loadDocs = defaultLoadDocs,
}: Props) {
  const [question, setQuestion] = useState("");
  const [answering, setAnswering] = useState(false);
  const [exchange, setExchange] = useState<Exchange | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [subjects, setSubjects] = useState<Subjects>({ status: "loading" });
  const [processing, setProcessing] = useState(0);
  const [noDocuments, setNoDocuments] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  // Only the URL the page opened with can name a thread to resume; later changes are the page's own.
  const [resumeId] = useState(() => searchParams.get(THREAD_PARAM));
  const alive = useRef(true);
  const busy = useRef(false);
  // The latest URL and setter, for the stream loop and the loading effect, which outlive a render.
  const url = useRef({ searchParams, setSearchParams });
  const questionBox = useRef<HTMLTextAreaElement>(null);
  // Set by Continue: the picker (and the focused Continue button) goes away once the answer starts, so focus
  // returns to the question box when the answer is done, or when the question comes back to it because it can't be
  // answered any more. Any other refused pick keeps the picker, which keeps focus.
  const focusQuestionWhenDone = useRef(false);

  useEffect(() => {
    url.current = { searchParams, setSearchParams };
  });

  useEffect(() => {
    if (!focusQuestionWhenDone.current || answering || busy.current) return;
    focusQuestionWhenDone.current = false;
    if (!exchange?.pending) questionBox.current?.focus();
  });

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  function keepThread(threadId: string) {
    url.current.setSearchParams(
      (params) => {
        const next = new URLSearchParams(params);
        next.set(THREAD_PARAM, threadId);
        return next;
      },
      { replace: true },
    );
  }

  function forgetThread() {
    if (!url.current.searchParams.has(THREAD_PARAM)) return;
    url.current.setSearchParams(
      (params) => {
        const next = new URLSearchParams(params);
        next.delete(THREAD_PARAM);
        return next;
      },
      { replace: true },
    );
  }

  // The subjects decide what the page is; the document count only feeds a hint, so its failure is not shown.
  // A thread in the URL that still waits for the pick comes back with its question and the learner's subjects;
  // an answered or missing thread starts a new conversation. A thread that couldn't be loaded keeps its id in the
  // URL, so reloading the page tries again.
  useEffect(() => {
    let current = true;
    const resuming: Promise<ThreadView | null | "failed"> = resumeId
      ? loadPending(resumeId).catch((error: unknown) => {
          if (error instanceof SessionExpiredError) throw error;
          return "failed" as const;
        })
      : Promise.resolve(null);
    Promise.all([loadSubjects(), resuming]).then(
      ([list, thread]) => {
        if (!current) return;
        if (list.length === 0) return setNoDocuments(true);
        setSubjects({ status: "ready", list });
        if (thread === "failed") setProblem({ message: RESUME_FAILURE });
        else if (thread?.awaiting_subjects) {
          setExchange({
            question: thread.question,
            subjects: [],
            answer: "",
            citations: [],
            pending: { threadId: thread.thread_id, subjects: list },
          });
        } else if (resumeId) forgetThread();
      },
      (error: unknown) => current && setSubjects({ status: error instanceof SessionExpiredError ? "ended" : "failed" }),
    );
    loadDocs().then(
      (docs) => current && setProcessing(docs.filter((d) => d.state === "processing").length),
      () => {},
    );
    return () => {
      current = false;
    };
    // forgetThread reads the URL through a ref, so changing the URL doesn't load everything again.
  }, [loadSubjects, loadDocs, loadPending, resumeId]);

  const trimmed = question.trim();
  const pending = exchange?.pending ?? null;
  const canAsk = !answering && !pending && trimmed.length > 0;

  function submit() {
    // The ref also stops a second Enter that lands before the disabled state renders.
    if (!canAsk || busy.current) return;
    setExchange({ question: trimmed, subjects: [], answer: "", citations: [], pending: null });
    setQuestion("");
    void consume(() => ask(trimmed));
  }

  function onContinue(subjectIds: string[]) {
    if (!exchange || !pending || busy.current) return;
    const { threadId } = pending;
    focusQuestionWhenDone.current = true;
    void consume(() => choose(threadId, subjectIds), exchange.question);
  }

  // Reads one answer stream, for a question or for the pick that lets a waiting question be answered (`waiting` is
  // that question, given back to the question box if it can't be answered any more).
  async function consume(open: () => AsyncIterable<ChatEvent>, waiting?: string) {
    busy.current = true;
    setAnswering(true);
    setProblem(null);
    // The protocol always ends with done or error; a stream that just stops (dropped connection) failed.
    let ended = false;
    try {
      for await (const event of open()) {
        if (!alive.current) break; // leaving the page stops reading, which closes the stream
        if (event.type === "done" || event.type === "error") ended = true;
        if (event.type === "thread") {
          setExchange((e) => e && { ...e, subjects: event.subjects, pending: null });
          forgetThread();
        } else if (event.type === "choose_subjects") {
          setExchange((e) => e && { ...e, pending: { threadId: event.thread_id, subjects: event.subjects } });
          keepThread(event.thread_id);
        } else if (event.type === "delta") setExchange((e) => e && { ...e, answer: e.answer + event.text });
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
      // The waiting question can't be answered any more (the thread is gone, or the tutor lost it): drop the picker
      // and the thread, and put the question back in the box (focused once answering ends) to ask it again.
      else if (error instanceof QuestionExpiredError) {
        setExchange(null);
        setQuestion(waiting ?? "");
        forgetThread();
        setProblem({ message: error.message });
      } else if (error instanceof AskRefusedError) setProblem({ message: error.message });
      // A SessionExpiredError was already reported by the API client; the session screen replaces this page.
      else if (!(error instanceof SessionExpiredError)) setProblem({ message: GENERIC_FAILURE });
    } finally {
      busy.current = false;
      if (alive.current) setAnswering(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  // Enter asks; Shift+Enter adds a line.
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
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

  if (subjects.status === "ended") return null;

  if (subjects.status !== "ready") {
    return (
      <div className={styles.column}>
        <PageHeader title="New conversation" description="Subjects appear after your first question." />
        {subjects.status === "failed" && (
          <p className={styles.problem}>Your subjects couldn't be loaded. Reload the page to try again.</p>
        )}
      </div>
    );
  }

  return (
    <div className={styles.column}>
      {exchange ? (
        <PageHeader
          title={exchange.question}
          titleClassName={styles.clampedTitle}
          description={exchange.pending ? "Subjects appear after your first question." : undefined}
          below={
            exchange.subjects.length > 0 && (
              <ul className={`${styles.chips} ${styles.headerChips}`} aria-label="Subjects">
                {exchange.subjects.map((s) => (
                  <li key={s.subject_id}>
                    <SubjectChip name={s.name} hueKey={s.subject_id} size="sm" />
                  </li>
                ))}
              </ul>
            )
          }
        />
      ) : (
        <>
          <PageHeader title="New conversation" description="Subjects appear after your first question." />
          <section className={styles.welcome}>
            <h2 className={styles.welcomeTitle}>Ask about your documents</h2>
            <p className={styles.welcomeText}>
              I work out which of your subjects a question is about, answer only from your documents, and show the page each
              answer came from.
            </p>
            <div className={styles.yourSubjects}>
              <span>Your subjects:</span>
              <ul className={styles.chips} aria-label="Your subjects">
                {subjects.list.map((s) => (
                  <li key={s.subject_id}>
                    <SubjectChip name={s.name} hueKey={s.subject_id} size="sm" />
                  </li>
                ))}
              </ul>
            </div>
          </section>
        </>
      )}

      {exchange && (
        <p className={styles.question}>
          <span className="visually-hidden">You asked: </span>
          {exchange.question}
        </p>
      )}

      {/* Announced once when the answer is complete, never word by word (DESIGN.md → Accessibility). */}
      <div className={styles.answerRegion} aria-live="polite" aria-busy={answering}>
        {/* While the thread waits for its subjects, the pick is the only action: the question box is disabled. */}
        {pending && (
          <ChooseSubjects key={pending.threadId} subjects={pending.subjects} busy={answering} onContinue={onContinue} />
        )}
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
        {problem && <p className={styles.problem}>{problem.message}</p>}
      </div>

      {answering && <p className={styles.thinking}>The tutor is answering…</p>}

      {processing > 0 && (
        <p className={styles.hint}>
          <Clock className={styles.hintIcon} strokeWidth={1.5} aria-hidden="true" />
          {processingHint(processing)}
        </p>
      )}

      <form className={styles.form} onSubmit={onSubmit}>
        <label htmlFor="chat-question" className="visually-hidden">
          Your question
        </label>
        <textarea
          ref={questionBox}
          id="chat-question"
          className={styles.input}
          rows={3}
          maxLength={MAX_QUESTION}
          placeholder="Ask about your documents"
          value={question}
          disabled={answering || pending !== null}
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
