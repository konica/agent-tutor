import { ArrowUp, CircleAlert, Clock, FileText, Filter, PanelLeft, Plus, Search, Upload } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import {
  addThreadDocuments,
  askInNewThread,
  askInThread,
  AskRefusedError,
  formatCitation,
  loadDocumentsUsed,
  NoDocumentsError,
  removeThreadDocument,
  renameConversation,
  setSearchScope,
  type ChatCitation,
  type ChatEvent,
  type SearchScope,
} from "../../api/chat";
import { loadDocuments } from "../../api/documents";
import type { DocumentResponse, ThreadDocumentResponse } from "../../api/generated/types.gen";
import { SessionExpiredError, sessionExpiry } from "../../auth/authClient";
import { Button } from "../../components/Button/Button";
import { IconButton } from "../../components/Button/IconButton";
import { LinkButton } from "../../components/Button/LinkButton";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import styles from "./ChatPage.module.css";
import { ConversationPanel } from "./ConversationPanel";
import { DocumentPicker } from "./DocumentPicker";
import { ThreadTitle } from "./ThreadTitle";
import { usePanelOpen } from "./usePanelOpen";

type Props = {
  /** Asks in a new thread. */
  ask?: (question: string) => AsyncIterable<ChatEvent>;
  /** Asks in an existing thread, within its search scope. */
  askIn?: (threadId: string, question: string) => AsyncIterable<ChatEvent>;
  loadDocs?: () => Promise<DocumentResponse[]>;
  loadUsed?: (threadId: string) => Promise<ThreadDocumentResponse[]>;
  loadReady?: () => Promise<DocumentResponse[]>;
  addDocs?: (threadId: string, documentIds: string[]) => Promise<ThreadDocumentResponse[]>;
  removeDoc?: (threadId: string, documentId: string) => Promise<void>;
  /** Resolves with the saved title. */
  rename?: (threadId: string, title: string) => Promise<string>;
  /** Resolves with the saved scope; a refusal rejects with the server's message. */
  setScope?: (threadId: string, scope: SearchScope) => Promise<SearchScope>;
};

type Exchange = {
  question: string;
  answer: string;
  citations: ChatCitation[];
  /** The limited decline's message: the conversation's documents don't cover the question. */
  declined: string | null;
};

// "ended" is a session that expired while loading: the session screen takes over, this page shows nothing.
type Library = { status: "loading" | "failed" | "ended" } | { status: "ready" };

type Problem = { message: string };

const MAX_QUESTION = 4000;
const PANEL_ID = "conversation-panel";
const GENERIC_FAILURE = "The tutor couldn't answer right now. Try again in a moment.";

const defaultAsk = (question: string) => askInNewThread(question);
const defaultAskIn = (threadId: string, question: string) => askInThread(threadId, question);
const defaultLoadDocs = () => loadDocuments();
const defaultLoadUsed = (threadId: string) => loadDocumentsUsed(threadId);
const defaultLoadReady = () => loadDocuments({ state: "ready" });
const defaultAddDocs = (threadId: string, documentIds: string[]) => addThreadDocuments(threadId, documentIds);
const defaultRemoveDoc = (threadId: string, documentId: string) => removeThreadDocument(threadId, documentId);
const defaultRename = (threadId: string, title: string) => renameConversation(threadId, title);
const defaultSetScope = (threadId: string, scope: SearchScope) => setSearchScope(threadId, scope);

const documentCount = (n: number) => (n === 1 ? "1 document" : `${n} documents`);

function errorMessage(error: unknown) {
  return error instanceof Error && error.message ? error.message : GENERIC_FAILURE;
}

function processingHint(count: number) {
  return count === 1
    ? "1 document is still processing and can't be used yet."
    : `${count} documents are still processing and can't be used yet.`;
}

// Single turn (#82): each question starts a new thread and replaces the previous exchange. A conversation limited to its
// documents (US-4c) is the exception: its questions are asked in the same thread, so its scope applies to them.
export function ChatPage({
  ask = defaultAsk,
  askIn = defaultAskIn,
  loadDocs = defaultLoadDocs,
  loadUsed = defaultLoadUsed,
  loadReady = defaultLoadReady,
  addDocs = defaultAddDocs,
  removeDoc = defaultRemoveDoc,
  rename = defaultRename,
  setScope: saveScope = defaultSetScope,
}: Props) {
  const [question, setQuestion] = useState("");
  const [answering, setAnswering] = useState(false);
  const [exchange, setExchange] = useState<Exchange | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [library, setLibrary] = useState<Library>({ status: "loading" });
  const [processing, setProcessing] = useState(0);
  const [noDocuments, setNoDocuments] = useState(false);
  const [used, setUsed] = useState<ThreadDocumentResponse[]>([]);
  const [usedFailed, setUsedFailed] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  // The conversation's first question titles it, until the learner renames it.
  const [firstQuestion, setFirstQuestion] = useState<string | null>(null);
  const [renamed, setRenamed] = useState<string | null>(null);
  const [scope, setScope] = useState<SearchScope>("library");
  const [answered, setAnswered] = useState(false);
  const [showCitations, setShowCitations] = useState(true);
  const [panelOpen, togglePanel] = usePanelOpen();
  const [pickerOpen, setPickerOpen] = useState(false);
  // Said by the status region once a document is added or removed (DESIGN.md → Accessibility).
  const [announcement, setAnnouncement] = useState("");
  // Bumped by Change under the composer: focus the panel's switch once the panel has rendered.
  const [focusSwitch, setFocusSwitch] = useState(0);
  const pageRef = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  const busy = useRef(false);
  const sourcesId = useId();
  // Counts questions, so a late documents-used reply never fills the panel of a newer conversation.
  const turn = useRef(0);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (focusSwitch > 0) pageRef.current?.querySelector<HTMLElement>("[data-scope-switch]")?.focus();
  }, [focusSwitch]);

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

  function submit() {
    // The ref also stops a second Enter that lands before the disabled state renders.
    if (!canAsk || busy.current) return;
    setQuestion("");
    // A limited conversation keeps its thread, so the limit applies; otherwise a question starts a new thread.
    void answer(trimmed, threadId !== null && scope === "listed" ? threadId : null);
  }

  // Asks in the given thread, or in a new one when it is null: the panel, the title, and the scope then start over.
  async function answer(text: string, inThread: string | null) {
    busy.current = true;
    setAnswering(true);
    setProblem(null);
    setExchange({ question: text, answer: "", citations: [], declined: null });
    let thisTurn = turn.current;
    if (inThread === null) {
      thisTurn = ++turn.current;
      setUsed([]);
      setUsedFailed(false);
      setThreadId(null);
      setFirstQuestion(text);
      setRenamed(null);
      setAnswered(false);
      setPickerOpen(false);
      setScope("library");
    }
    await run(() => (inThread === null ? ask(text) : askIn(inThread, text)), thisTurn);
  }

  // Reads one answer's events into the exchange. The protocol always ends with done or error; a stream that just stops
  // (dropped connection) failed.
  async function run(events: () => AsyncIterable<ChatEvent>, thisTurn: number) {
    let ended = false;
    let done = false;
    let thread: string | null = null;
    try {
      for await (const event of events()) {
        if (!alive.current) break; // leaving the page stops reading, which closes the stream
        if (event.type === "done" || event.type === "error") ended = true;
        if (event.type === "done") done = true;
        if (event.type === "thread") {
          thread = event.thread_id;
          setThreadId(thread);
        } else if (event.type === "delta") setExchange((e) => e && { ...e, answer: e.answer + event.text });
        else if (event.type === "citations") setExchange((e) => e && { ...e, citations: event.citations });
        else if (event.type === "decline") setExchange((e) => e && { ...e, declined: event.message });
        else if (event.type === "error") {
          // The token stopped working mid-answer: the session screen asks the learner to sign in again.
          if (event.code === "unauthenticated") sessionExpiry.notify();
          else setProblem({ message: event.message });
        }
      }
      // Any partial answer stays visible above the message.
      if (alive.current && !ended) setProblem({ message: GENERIC_FAILURE });
      // A decline used no documents; reloading the list is harmless.
      if (alive.current && done && thread) {
        setAnswered(true);
        void showDocumentsUsed(thread, thisTurn);
      }
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

  // The panel's switch. A failure keeps the switch as it was and says why; a SessionExpiredError was already reported.
  async function changeSearchScope(threadId: string, listed: boolean) {
    const forTurn = turn.current;
    try {
      const saved = await saveScope(threadId, listed ? "listed" : "library");
      if (!alive.current || turn.current !== forTurn) return;
      setScope(saved);
      setAnnouncement(saved === "listed" ? `Only searching ${documentCount(used.length)}.` : "Searching all your documents.");
    } catch (error) {
      if (alive.current && !(error instanceof SessionExpiredError)) setAnnouncement(errorMessage(error));
    }
  }

  // The limited decline's way out: turn the limit off, then ask the same question again in the conversation. If the
  // limit can't be turned off, the problem line says why and nothing is asked.
  async function searchAll(threadId: string, text: string) {
    if (busy.current) return;
    busy.current = true;
    setProblem(null);
    try {
      await saveScope(threadId, "library");
    } catch (error) {
      busy.current = false;
      if (alive.current && !(error instanceof SessionExpiredError)) setProblem({ message: errorMessage(error) });
      return;
    }
    if (!alive.current) return;
    setScope("library");
    await answer(text, threadId);
  }

  // Change under the composer: opens the panel when it is closed, then moves focus to its switch.
  function changeScope() {
    if (!panelOpen) togglePanel();
    setFocusSwitch((n) => n + 1);
  }

  // Shows a thread's documents. The server turns the limit off once the list is empty, and so does the page.
  function showList(documents: ThreadDocumentResponse[]) {
    setUsed(documents);
    if (documents.length === 0) setScope("library");
  }

  // The server recorded the documents the answer drew on before it sent done. A failure says so in the panel, so an
  // empty list never reads as "nothing was used"; a SessionExpiredError was already reported by the API client.
  async function showDocumentsUsed(threadId: string, forTurn: number) {
    try {
      const documents = await loadUsed(threadId);
      if (alive.current && turn.current === forTurn) showList(documents);
    } catch {
      // The answer is complete either way; only the panel's list is missing.
      if (alive.current && turn.current === forTurn) setUsedFailed(true);
    }
  }

  // Rejecting keeps the picker open with its error; a SessionExpiredError was already reported by the API client.
  async function addDocuments(threadId: string, documentIds: string[]) {
    const forTurn = turn.current;
    const documents = await addDocs(threadId, documentIds);
    if (!alive.current || turn.current !== forTurn) return;
    showList(documents);
    setUsedFailed(false);
    setPickerOpen(false);
    setAnnouncement(`${documentCount(documentIds.length)} added to this conversation.`);
  }

  // Optimistic: the row goes at once (the panel moves focus to the next row); a failure reloads the list so the panel
  // shows the truth. A SessionExpiredError was already reported; the session screen replaces this page.
  async function removeDocument(threadId: string, documentId: string) {
    const forTurn = turn.current;
    const removed = used.find((d) => d.document_id === documentId);
    const scopeBefore = scope;
    showList(used.filter((d) => d.document_id !== documentId));
    if (removed) setAnnouncement(`${removed.title} removed from this conversation.`);
    try {
      await removeDoc(threadId, documentId);
    } catch (error) {
      if (!alive.current || turn.current !== forTurn || error instanceof SessionExpiredError) return;
      // The server kept the document, so it kept the limit too.
      setScope(scopeBefore);
      void showDocumentsUsed(threadId, forTurn);
    }
  }

  // A refusal rejects with the server's message, which the title field shows.
  async function renameTitle(newTitle: string) {
    if (threadId === null) return;
    const forTurn = turn.current;
    const saved = await rename(threadId, newTitle);
    if (alive.current && turn.current === forTurn) setRenamed(saved);
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
      <div className={styles.fallback}>
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
      </div>
    );
  }

  if (library.status === "ended") return null;

  if (library.status !== "ready") {
    return (
      <div className={styles.fallback}>
        <div className={styles.column}>
          <PageHeader title="New conversation" />
          {library.status === "failed" && (
            <p className={styles.problem}>
              <CircleAlert className={styles.problemIcon} strokeWidth={1.5} aria-hidden="true" />
              Your documents couldn't be loaded. Reload the page to try again.
            </p>
          )}
        </div>
      </div>
    );
  }

  // A citation to a deleted document keeps its [n] but loses the title and page: references read "Deleted document".
  const deletedIds = new Set(used.filter((d) => d.deleted).map((d) => d.document_id));
  // The title starts as the first question until the learner renames it (PRD §9.4).
  const title = renamed ?? firstQuestion ?? "New conversation";
  const toggleLabel = panelOpen ? "Hide panel" : "Show panel";

  return (
    <div ref={pageRef} className={styles.page}>
      {/* One 40px row: the panel toggle and the conversation's title (DESIGN.md → Chat). */}
      <header className={styles.header}>
        <button
          type="button"
          className={styles.toggle}
          aria-label={toggleLabel}
          title={toggleLabel}
          aria-expanded={panelOpen}
          aria-controls={PANEL_ID}
          onClick={togglePanel}
        >
          <PanelLeft className={styles.toggleIcon} strokeWidth={1.5} aria-hidden="true" />
        </button>
        {/* Editable once the server has started the conversation (US-13). */}
        <ThreadTitle title={title} editable={threadId !== null} onRename={renameTitle} />
      </header>

      <p role="status" className="visually-hidden">
        {announcement}
      </p>

      <div className={`${styles.body} ${panelOpen ? styles.withPanel : ""}`}>
        {panelOpen && (
          <ConversationPanel
            id={PANEL_ID}
            documents={used}
            documentsFailed={usedFailed}
            threadId={threadId}
            answered={answered}
            showCitations={showCitations}
            onShowCitationsChange={setShowCitations}
            onAddDocuments={() => setPickerOpen(true)}
            onRemoveDocument={threadId === null ? undefined : (documentId) => void removeDocument(threadId, documentId)}
            searchListed={scope === "listed"}
            onSearchListedChange={threadId === null ? undefined : (on) => void changeSearchScope(threadId, on)}
          />
        )}
        {pickerOpen && threadId !== null && (
          <DocumentPicker
            listedIds={new Set(used.map((d) => d.document_id))}
            loadReady={loadReady}
            onAdd={(documentIds) => addDocuments(threadId, documentIds)}
            onClose={() => setPickerOpen(false)}
          />
        )}

        {/* The messages scroll; the composer row stays pinned under them (DESIGN.md → Chat). */}
        <div className={styles.conversation}>
          <div className={styles.messages}>
            <div className={styles.column}>
              {!exchange && (
                <section className={styles.welcome}>
                  <h2 className={styles.welcomeTitle}>Ask about your documents</h2>
                  <p className={styles.welcomeText}>
                    I answer only from the documents in your Library and show the page each answer came from. There's
                    nothing to choose first: just ask.
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
                {exchange?.declined != null ? (
                  <div className={styles.declineCard}>
                    <p>{exchange.declined}</p>
                    <p className={styles.muted}>This conversation only searches {documentCount(used.length)}.</p>
                    <div className={styles.declineActions}>
                      <Button icon={Plus} aria-haspopup="dialog" disabled={answering} onClick={() => setPickerOpen(true)}>
                        Add documents
                      </Button>
                      <Button
                        icon={Search}
                        disabled={answering || threadId === null}
                        onClick={() => threadId !== null && void searchAll(threadId, exchange.question)}
                      >
                        Search all my documents
                      </Button>
                    </div>
                  </div>
                ) : (
                  exchange?.answer && <p className={styles.answer}>{exchange.answer}</p>
                )}
                {exchange && exchange.declined === null && showCitations && exchange.citations.length > 0 && (
                  <div className={styles.sources}>
                    <span className={styles.sourcesLabel} id={sourcesId}>
                      Sources
                    </span>
                    {/* Each source shows the [n] the answer's text uses for it; an answer may cite [2] without [1]. */}
                    <ul className={styles.sourceList} aria-labelledby={sourcesId}>
                      {exchange.citations.map((c) =>
                        deletedIds.has(c.document_id) ? (
                          <li key={c.chunk_id}>
                            <span className={`${styles.source} ${styles.sourceDeleted}`} title="Deleted document">
                              <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
                              <span className={styles.sourceMarker}>[{c.n}]</span> Deleted document
                            </span>
                          </li>
                        ) : (
                          <li key={c.chunk_id}>
                            <span className={styles.source} title={formatCitation(c)}>
                              <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
                              <span className={styles.sourceMarker}>[{c.n}]</span>{" "}
                              <span className={styles.sourceTitle}>{c.document_title}</span>{" "}
                              <span>· {c.page === null ? "page unavailable" : `p. ${c.page}`}</span>
                            </span>
                          </li>
                        ),
                      )}
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
            </div>
          </div>

          <form className={styles.form} onSubmit={onSubmit}>
            <label htmlFor="chat-question" className="visually-hidden">
              Your question
            </label>
            {scope === "listed" && (
              <p className={styles.scopeLine}>
                <Filter className={styles.scopeIcon} strokeWidth={1.5} aria-hidden="true" />
                {`Searching ${documentCount(used.length)} `}
                <button type="button" className={styles.linkButton} onClick={changeScope}>
                  Change
                </button>
              </p>
            )}
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
              <IconButton
                type="submit"
                label="Ask"
                icon={ArrowUp}
                tip={false}
                disabled={!canAsk}
                className={styles.send}
              />
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
      </div>
    </div>
  );
}
