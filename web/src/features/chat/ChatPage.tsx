import {
  Archive,
  ArchiveRestore,
  ArrowDown,
  ArrowUp,
  CircleAlert,
  Clock,
  FileText,
  Filter,
  MessageSquare,
  MessageSquareX,
  PanelLeft,
  Plus,
  Search,
  SquarePen,
  Upload,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";

import {
  addThreadDocuments,
  askInNewThread,
  askInThread,
  AskRefusedError,
  ConversationNotFoundError,
  loadConversation as loadConversationApi,
  loadDocumentsUsed,
  rateAnswer,
  removeThreadDocument,
  renameConversation,
  setSearchScope,
  type ChatCitation,
  type ChatEvent,
  type Conversation,
  type Rating,
  type SearchScope,
} from "../../api/chat";
import { archiveConversation, restoreConversation } from "../../api/conversations";
import { loadDocuments } from "../../api/documents";
import type { DocumentResponse, ThreadDocumentResponse } from "../../api/generated/types.gen";
import { useConversations } from "../../app/conversations";
import { SessionExpiredError, sessionExpiry } from "../../auth/authClient";
import { Banner } from "../../components/Banner/Banner";
import { Button } from "../../components/Button/Button";
import { IconButton } from "../../components/Button/IconButton";
import { LinkButton } from "../../components/Button/LinkButton";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { useForceNavRail } from "../../components/AppShell/NavRail";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { DocumentPane } from "../viewer/DocumentPane";
import type { Passage } from "../viewer/DocumentViewer";
import type { ViewerDeps } from "../viewer/ViewerDialog";
import { Answer } from "./Answer";
import styles from "./ChatPage.module.css";
import { AnswerRating } from "./AnswerRating";
import { ConversationPanel } from "./ConversationPanel";
import { DocumentPicker } from "./DocumentPicker";
import { ThreadTitle } from "./ThreadTitle";
import { useChatScroll } from "./useChatScroll";
import { usePanelOpen } from "./usePanelOpen";

type Props = {
  /** Asks in a new thread; `documentId` is the document the conversation starts from (`/chat?document=<id>`), sent
   * with the first question only. */
  ask?: (question: string, documentId?: string) => AsyncIterable<ChatEvent>;
  /** Asks in an existing thread, within its search scope. */
  askIn?: (threadId: string, question: string) => AsyncIterable<ChatEvent>;
  loadDocs?: () => Promise<DocumentResponse[]>;
  loadUsed?: (threadId: string) => Promise<ThreadDocumentResponse[]>;
  loadReady?: () => Promise<DocumentResponse[]>;
  addDocs?: (threadId: string, documentIds: string[]) => Promise<ThreadDocumentResponse[]>;
  removeDoc?: (threadId: string, documentId: string) => Promise<void>;
  /** Resolves with the saved title. */
  rename?: (threadId: string, title: string) => Promise<string>;
  /** Test seam: the document viewer's file link, PDF loader, and restore. */
  viewerDeps?: ViewerDeps;
  /** Resolves with the saved scope; a refusal rejects with the server's message. */
  setScope?: (threadId: string, scope: SearchScope) => Promise<SearchScope>;
  /** The conversation `/chat/<id>` names; rejects with ConversationNotFoundError for an unknown or another learner's. */
  loadConversation?: (threadId: string) => Promise<Conversation>;
  /** Resolves with the saved rating; a failure rejects. */
  rate?: (threadId: string, runId: string, rating: Rating) => Promise<Rating>;
  /** Archive and restore the conversation (US-13); a failure rejects. */
  archive?: (threadId: string) => Promise<unknown>;
  restore?: (threadId: string) => Promise<unknown>;
};

type Exchange = {
  question: string;
  answer: string;
  citations: ChatCitation[];
  /** A turn the tutor didn't answer: "limited" (the conversation's documents don't cover it), "no_documents" (nothing
   * can be read: the request to upload a document), or "off_topic" (not a study question: the message alone). */
  decline: { code: string; message: string } | null;
  /** The turn's run, which a rating names; null until the server has started it, and for turns saved before ratings. */
  runId: string | null;
  rating: Rating | null;
  /** The stream ended with done: only then was the turn saved, so only then can it be rated. */
  kept: boolean;
};

// "ended" is a session that expired while loading: the session screen takes over, this page shows nothing.
type Library = { status: "loading" | "failed" | "ended" } | { status: "ready" };

type Problem = { message: string };

// Loading the conversation a URL names; "none" once it is shown, or at /chat.
type Opened = { status: "none" | "loading" | "not-found" | "failed" };

// `chunkId`, `turn`, and `passage` are set only when a Sources chip or an answer's marker opened the document; a panel
// row's open leaves them out. `turn` tells apart the same passage cited in two turns.
type Viewer = { documentId: string; chunkId?: string; turn?: number; passage?: Passage };

const MAX_QUESTION = 4000;
const PANEL_ID = "conversation-panel";
const GENERIC_FAILURE = "The tutor couldn't answer right now. Try again in a moment.";

const defaultAsk = (question: string, documentId?: string) => askInNewThread(question, documentId);
const defaultAskIn = (threadId: string, question: string) => askInThread(threadId, question);
const defaultLoadDocs = () => loadDocuments();
const defaultLoadUsed = (threadId: string) => loadDocumentsUsed(threadId);
const defaultLoadReady = () => loadDocuments({ state: "ready" });
const defaultAddDocs = (threadId: string, documentIds: string[]) => addThreadDocuments(threadId, documentIds);
const defaultRemoveDoc = (threadId: string, documentId: string) => removeThreadDocument(threadId, documentId);
const defaultRename = (threadId: string, title: string) => renameConversation(threadId, title);
const defaultSetScope = (threadId: string, scope: SearchScope) => setSearchScope(threadId, scope);
const defaultLoadConversation = (threadId: string) => loadConversationApi(threadId);
const defaultRate = (threadId: string, runId: string, rating: Rating) => rateAnswer(threadId, runId, rating);
const defaultArchive = (threadId: string) => archiveConversation(threadId);
const defaultRestore = (threadId: string) => restoreConversation(threadId);

const documentCount = (n: number) => (n === 1 ? "1 document" : `${n} documents`);

function errorMessage(error: unknown) {
  return error instanceof Error && error.message ? error.message : GENERIC_FAILURE;
}

// The starting document as the panel lists it before the thread exists: added by the learner, not used yet.
function asListed(d: DocumentResponse): ThreadDocumentResponse {
  return {
    document_id: d.document_id,
    title: d.title,
    authors: d.authors,
    year: d.year,
    archived: false,
    deleted: false,
    added_by: "learner",
    used: false,
  };
}

function processingHint(count: number) {
  return count === 1
    ? "1 document is still processing and can't be used yet."
    : `${count} documents are still processing and can't be used yet.`;
}

// The first question starts a thread (and moves to its URL); every later question is asked in it and adds a turn under
// the history, whether or not its search is limited (US-4c). New conversation in the header, or the Chat nav, starts
// over at /chat. `/chat/<id>` reopens a conversation with its turns (US-13). An archived conversation is read-only
// (US-13): a banner offers Restore, and the composer, the title, and the panel's document controls are off; its
// citations, documents, and ratings still work.
export function ChatPage({
  ask = defaultAsk,
  askIn = defaultAskIn,
  loadDocs = defaultLoadDocs,
  loadUsed = defaultLoadUsed,
  loadReady = defaultLoadReady,
  addDocs = defaultAddDocs,
  removeDoc = defaultRemoveDoc,
  rename = defaultRename,
  viewerDeps,
  setScope: saveScope = defaultSetScope,
  loadConversation = defaultLoadConversation,
  rate = defaultRate,
  archive = defaultArchive,
  restore = defaultRestore,
}: Props) {
  const conversations = useConversations();
  const [question, setQuestion] = useState("");
  const [answering, setAnswering] = useState(false);
  const [turns, setTurns] = useState<Exchange[]>([]);
  const [opened, setOpened] = useState<Opened>({ status: "none" });
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
  const [archived, setArchived] = useState(false);
  // Set while an archive or restore request is in flight: the Actions and the banner's Restore are off meanwhile.
  const [changingStatus, setChangingStatus] = useState(false);
  const statusProblem = useRef<string | null>(null); // the message changeArchived last showed, to clear only that one
  // Where focus goes once an archive or restore has rendered: the panel's action that replaced the one clicked, or the
  // composer that came back.
  const [focusAfterStatus, setFocusAfterStatus] = useState<"action" | "composer" | "banner" | null>(null);
  const [focusQuestion, setFocusQuestion] = useState(false);
  const [storedOpen, togglePanel] = usePanelOpen();
  // A starting document opens the panel once without saving it, so the learner's remembered choice stays as it was.
  const [forceOpen, setForceOpen] = useState(false);
  const panelOpen = storedOpen || forceOpen;
  const [pickerOpen, setPickerOpen] = useState(false);
  // Said by the status region once a document is added or removed (DESIGN.md → Accessibility).
  const [announcement, setAnnouncement] = useState("");
  // The document open beside the conversation (DESIGN.md → Chat, Split view). While it is open the panel collapses
  // and the nav drops to its rail; the header toggle then shows the panel for this split only, never saving the choice.
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [panelDuringViewer, setPanelDuringViewer] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const restoreFocus = useRef(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  useForceNavRail(viewer !== null);
  // Bumped by Change under the composer: focus the panel's switch once the panel has rendered.
  const [focusSwitch, setFocusSwitch] = useState(0);
  const pageRef = useRef<HTMLDivElement>(null);
  // The document from `/chat?document=<id>` (US-4b), until the first question takes it or the learner removes it.
  // Read once: the param is cleared from the URL once used or dropped, which must not reload the page's documents.
  const [searchParams, setSearchParams] = useSearchParams();
  const [startId] = useState(() => searchParams.get("document"));
  const [starting, setStarting] = useState<DocumentResponse | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const alive = useRef(true);
  const rateRequests = useRef<Record<string, number>>({});
  const usedRequests = useRef(0);
  const busy = useRef(false);
  // Counts the conversations shown (a new one at /chat, or one a URL opens), so a late reply or stream event of an
  // earlier one never reaches a newer one. A question in the same conversation keeps it.
  const turn = useRef(0);
  // The messages pane follows new text only while the learner is at the bottom (DESIGN.md → Chat).
  const scroll = useChatScroll([turns, answering, problem]);
  const { threadId: routeThreadId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // The conversation the page shows, by its URL or just created: null at /chat.
  const shown = useRef<string | null>(null);
  // The navigation last handled, and whether the page made the next one itself (dropping the starting document's param).
  const seenKey = useRef(location.key);
  const ownNavigation = useRef(false);

  // The URL names the conversation. A change the page made itself (a new thread's URL) is already shown; any other
  // change (reload, Back, a pasted link, the Chat nav) opens that conversation, or a new one at /chat. The Chat nav
  // clicked at /chat (say, under a first question that failed) starts over too. Runs only when the location changes.
  useEffect(() => {
    const target = routeThreadId ?? null;
    const visit = location.key !== seenKey.current && !ownNavigation.current;
    seenKey.current = location.key;
    ownNavigation.current = false;
    if (target === shown.current && !(target === null && visit)) return;
    shown.current = target;
    if (target === null) reset();
    else void openConversation(target);
  }, [routeThreadId, location.key]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (focusSwitch > 0) pageRef.current?.querySelector<HTMLElement>("[data-scope-switch]")?.focus();
  }, [focusSwitch]);

  // The clicked Archive or Restore is gone once the status has changed. Runs after that render: the composer is enabled
  // again, and the panel shows its other action, or the panel toggle takes focus while the panel is hidden.
  useEffect(() => {
    if (focusAfterStatus === null) return;
    setFocusAfterStatus(null);
    if (focusAfterStatus === "composer") input.current?.focus();
    else if (focusAfterStatus === "banner") {
      (pageRef.current?.querySelector<HTMLElement>("[data-banner-restore]") ?? pageRef.current?.querySelector<HTMLElement>("[data-thread-action]") ?? toggleRef.current)?.focus();
    } else (pageRef.current?.querySelector<HTMLElement>("[data-thread-action]") ?? toggleRef.current)?.focus();
  }, [focusAfterStatus]);

  // After New conversation the question box takes focus, once it is enabled again: the button may be clicked mid-answer,
  // and the page clears in the render after it.
  useEffect(() => {
    if (!focusQuestion || answering) return;
    setFocusQuestion(false);
    input.current?.focus();
  }, [focusQuestion, answering]);

  // The documents decide what a new conversation is: none ready → upload first; still processing → a hint. A
  // conversation opened from its URL shows its history either way.
  useEffect(() => {
    let current = true;
    loadDocs().then(
      (docs) => {
        if (!current) return;
        setProcessing(docs.filter((d) => d.state === "processing").length);
        // Only the learner's ready, non-archived document can start a conversation; any other id is ignored.
        setStarting(docs.find((d) => d.document_id === startId && d.state === "ready" && !d.archived) ?? null);
        setLibrary({ status: "ready" });
        if (!docs.some((d) => d.state === "ready")) setNoDocuments(true);
      },
      (error: unknown) => current && setLibrary({ status: error instanceof SessionExpiredError ? "ended" : "failed" }),
    );
    return () => {
      current = false;
    };
  }, [loadDocs, startId]);

  // A starting document is shown in the panel, so the panel opens; the learner can type their question at once.
  const hasStarting = starting !== null && library.status === "ready";
  useEffect(() => {
    if (!hasStarting) return;
    if (!storedOpen) setForceOpen(true);
    input.current?.focus();
    // Only when a starting document appears: closing the panel afterwards is the learner's choice.
  }, [hasStarting]);

  // The learner's toggle is remembered as before. Closing a panel the page opened for them keeps the saved "closed".
  function toggle() {
    const overridden = forceOpen && !storedOpen;
    setForceOpen(false);
    if (!overridden) togglePanel();
  }

  // Once the starting document is used or dropped, a reload or Back doesn't bring it back.
  function forgetStartParam() {
    if (!searchParams.has("document")) return;
    ownNavigation.current = true;
    setSearchParams(
      (params) => {
        params.delete("document");
        return params;
      },
      { replace: true },
    );
  }

  // Only before the first question: a starting document never replaces a live conversation's list.
  const pendingStart = threadId === null && turns.length === 0 ? starting : null;

  // Once the pane has closed, focus goes back to the row that opened it. The panel re-mounts on close, so the row is
  // a new element: find it again by its document id. If it is not on screen (the panel stays hidden), the panel
  // toggle takes focus instead.
  useEffect(() => {
    if (viewer !== null || !restoreFocus.current) return;
    restoreFocus.current = false;
    const from = opener.current;
    opener.current = null;
    const id = from?.dataset.documentId;
    const rows = Array.from(document.querySelectorAll<HTMLElement>(`#${PANEL_ID} [data-document-id]`));
    const live = from?.isConnected ? from : rows.find((row) => row.dataset.documentId === id);
    // A Sources chip hidden again by Show less can't take focus: its answer's Show N more button does.
    const hiddenList = live?.closest<HTMLElement>("ul[hidden]");
    const more = hiddenList ? document.querySelector<HTMLElement>(`[aria-controls="${hiddenList.id}"]`) : null;
    // Sources chips and answer markers stay mounted while the pane is open, so they take focus back directly. The toggle
    // is the fallback for a row that is no longer shown.
    ((hiddenList ? more : live) ?? toggleRef.current)?.focus();
  }, [viewer]);

  // Another row swaps the document in place; the pane moves focus to the new title.
  function openDocument(documentId: string, from: HTMLElement) {
    opener.current = from;
    setViewer({ documentId });
  }

  // A Sources chip or an answer's marker opens its document at the cited passage. `passage` is a new object on every
  // click, so clicking it again jumps back to it; a citation without a page opens the document at page 1.
  function openCitation(c: ChatCitation, turnIndex: number, from: HTMLElement) {
    opener.current = from;
    setViewer({
      documentId: c.document_id,
      chunkId: c.chunk_id,
      turn: turnIndex,
      passage: c.page === null ? undefined : { chunkId: c.chunk_id, page: c.page },
    });
  }

  function closeDocument() {
    restoreFocus.current = true;
    setViewer(null);
    setPanelDuringViewer(false);
  }

  const trimmed = question.trim();
  // An archived conversation takes no questions until it is restored; the server refuses them too. Nor does one whose URL
  // is still loading: its question belongs in it, not in a new thread.
  const canAsk = !answering && !archived && !changingStatus && opened.status === "none" && trimmed.length > 0;

  function submit() {
    // The ref also stops a second Enter that lands before the disabled state renders.
    if (!canAsk || busy.current) return;
    setQuestion("");
    // Once the conversation exists, every question is asked in it, within its search scope.
    void answer(trimmed, threadId);
  }

  // New conversation in the header: /chat, empty. From a conversation's URL it is a push, so Back returns to it; at /chat
  // (a first question still before its thread, or one that failed) the page just starts over. Either way a stream being
  // read stops, and none of its late events reach the new page.
  function newConversation() {
    // `shown`, not the route: a new thread's own URL may not have rendered yet.
    if (shown.current === null) reset();
    else navigate("/chat");
    setFocusQuestion(true);
  }

  // Clears the page for another conversation: a new one at /chat, or the one a URL opens. Bumping `turn` drops the late
  // replies and stream events of the conversation shown before. A starting document not yet asked about goes too.
  function reset() {
    ++turn.current;
    busy.current = false;
    setAnswering(false);
    setTurns([]);
    // The next conversation opens on its newest turn.
    scroll.land();
    setProblem(null);
    setOpened({ status: "none" });
    setUsed([]);
    setUsedFailed(false);
    setThreadId(null);
    setFirstQuestion(null);
    setRenamed(null);
    setAnswered(false);
    setPickerOpen(false);
    setScope("library");
    setArchived(false);
    setChangingStatus(false);
    // The document closes (the panel starts over); focus stays where the learner is.
    opener.current = null;
    setViewer(null);
    setPanelDuringViewer(false);
    setStarting(null);
    forgetStartParam();
  }

  // Shows the conversation a URL names: its title, scope, turns, and documents used.
  async function openConversation(id: string) {
    reset();
    const forTurn = turn.current;
    setOpened({ status: "loading" });
    try {
      const { thread, turns } = await loadConversation(id);
      if (!alive.current || turn.current !== forTurn) return;
      setThreadId(thread.thread_id);
      setFirstQuestion(thread.title ?? null);
      setScope(thread.search_scope);
      setArchived(thread.status === "archived");
      setTurns(
        turns.map((t) => ({
          question: t.question,
          answer: t.answer,
          citations: t.citations,
          decline: t.decline ?? null,
          runId: t.run_id ?? null,
          rating: t.rating ?? null,
          kept: true,
        })),
      );
      setAnswered(turns.length > 0);
      setOpened({ status: "none" });
      // Its list agrees with the scope: the server turns the limit off for an empty list, as showList does.
      void showDocumentsUsed(thread.thread_id, forTurn);
    } catch (error) {
      // A SessionExpiredError was already reported by the API client; the session screen replaces this page.
      if (!alive.current || turn.current !== forTurn || error instanceof SessionExpiredError) return;
      setOpened({ status: error instanceof ConversationNotFoundError ? "not-found" : "failed" });
    }
  }

  // Asks in the given thread, adding a turn under the history, or starts the conversation's thread when it is null. A
  // document open beside the conversation stays open either way.
  async function answer(text: string, inThread: string | null) {
    // The starting document goes with the first question only.
    let documentId: string | undefined;
    if (inThread === null) {
      documentId = pendingStart?.document_id;
      // A first question that failed before its thread existed was never saved: asking again replaces it.
      setTurns([]);
      setFirstQuestion(text);
      setStarting(null);
      forgetStartParam();
    }
    busy.current = true;
    setAnswering(true);
    setProblem(null);
    const asked: Exchange = { question: text, answer: "", citations: [], decline: null, runId: null, rating: null, kept: false };
    setTurns((list) => [...list, asked]);
    // The question scrolls into view, and the answer is followed from the bottom.
    scroll.toLatest();
    await run(() => (inThread === null ? ask(text, documentId) : askIn(inThread, text)), turn.current, inThread === null);
  }

  // Stream events fill the turn being answered: the last one.
  const updateLast = (change: (e: Exchange) => Exchange) =>
    setTurns((list) => (list.length === 0 ? list : [...list.slice(0, -1), change(list[list.length - 1]!)]));

  // Reads one answer's events into the last turn. The protocol always ends with done or error; a stream that just stops
  // (dropped connection) failed. A new thread moves to its URL once the server has created it.
  async function run(events: () => AsyncIterable<ChatEvent>, thisTurn: number, newThread: boolean) {
    // Leaving the page, or this conversation for another, stops reading, which closes the stream.
    const current = () => alive.current && turn.current === thisTurn;
    let ended = false;
    let done = false;
    let thread: string | null = null;
    try {
      for await (const event of events()) {
        if (!current()) break;
        if (event.type === "done" || event.type === "error") ended = true;
        if (event.type === "done") {
          done = true;
          updateLast((e) => ({ ...e, kept: true }));
        }
        if (event.type === "thread") {
          thread = event.thread_id;
          if (newThread) {
            // A push, so Back returns to the conversation shown before. Marked shown first: the page stays as it is.
            shown.current = thread;
            navigate(`/chat/${thread}`);
          }
          setThreadId(thread);
          updateLast((e) => ({ ...e, runId: event.run_id }));
        } else if (event.type === "delta") {
          updateLast((e) => ({ ...e, answer: e.answer + event.text }));
          // The server found readable documents after all (one was uploaded elsewhere): no longer the empty-library state.
          setNoDocuments(false);
        } else if (event.type === "citations") {
          updateLast((e) => ({ ...e, citations: event.citations }));
          setNoDocuments(false);
        }
        else if (event.type === "decline") {
          updateLast((e) => ({ ...e, decline: { code: event.code, message: event.message } }));
          if (event.code === "no_documents") setNoDocuments(true);
        }
        // A guard tripped (US-6): its message takes the partial answer's place, as a plain decline with no way out.
        else if (event.type === "replace") {
          updateLast((e) => ({ ...e, answer: "", citations: [], decline: { code: event.code, message: event.text } }));
        }
        else if (event.type === "error") {
          // The token stopped working mid-answer: the session screen asks the learner to sign in again.
          if (event.code === "unauthenticated") sessionExpiry.notify();
          else setProblem({ message: event.message });
        }
      }
      if (!current()) return;
      // Any partial answer stays visible above the message.
      if (!ended) setProblem({ message: GENERIC_FAILURE });
      // The answered conversation moves to the top of the shell's list. An error or a dropped stream after the thread
      // started still updated its last activity on the server.
      if (done || thread) conversations.refresh();
      // A decline used no documents; reloading the list is harmless.
      if (done && thread) {
        setAnswered(true);
        void showDocumentsUsed(thread, thisTurn);
      }
    } catch (error) {
      if (!current()) return;
      // A stream that broke after the thread started: the server updated its last activity.
      if (thread) conversations.refresh();
      if (error instanceof AskRefusedError) setProblem({ message: error.message });
      // A SessionExpiredError was already reported by the API client; the session screen replaces this page.
      else if (!(error instanceof SessionExpiredError)) setProblem({ message: GENERIC_FAILURE });
    } finally {
      // Otherwise a newer conversation has already reset these.
      if (turn.current === thisTurn) {
        busy.current = false;
        if (alive.current) setAnswering(false);
      }
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
    const forTurn = turn.current;
    busy.current = true;
    setProblem(null);
    try {
      await saveScope(threadId, "library");
    } catch (error) {
      if (turn.current !== forTurn) return;
      busy.current = false;
      if (alive.current && !(error instanceof SessionExpiredError)) setProblem({ message: errorMessage(error) });
      return;
    }
    // The learner left for another conversation meanwhile: nothing is asked there.
    if (!alive.current || turn.current !== forTurn) return;
    setScope("library");
    await answer(text, threadId);
  }

  // Change under the composer: opens the panel when it is closed, then moves focus to its switch. Beside a document the
  // panel shows for this split only, as with the header toggle.
  function changeScope() {
    if (viewer) setPanelDuringViewer(true);
    else if (!panelOpen) togglePanel();
    setFocusSwitch((n) => n + 1);
  }

  // Shows a thread's documents. The server turns the limit off once the list is empty, and so does the page.
  function showList(documents: ThreadDocumentResponse[]) {
    setUsed(documents);
    if (documents.length === 0) setScope("library");
  }

  // The server recorded the documents the answer drew on before it sent done. A failure says so in the panel, so an
  // empty list never reads as "nothing was used", until a later answer loads the list; a SessionExpiredError was already
  // reported by the API client.
  async function showDocumentsUsed(threadId: string, forTurn: number) {
    // Follow-ups reload the same thread's list: only the newest load may show, as replies can arrive out of order.
    const request = ++usedRequests.current;
    const current = () => alive.current && turn.current === forTurn && usedRequests.current === request;
    try {
      const documents = await loadUsed(threadId);
      if (!current()) return;
      showList(documents);
      setUsedFailed(false);
    } catch {
      // The answer is complete either way; only the panel's list is missing.
      if (current()) setUsedFailed(true);
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
    // Removing the open document closes the pane. Its row is gone, so focus doesn't go back to it: while the panel stays
    // shown, the panel moves focus to the next row; if it hides with the pane (its saved state is hidden), the toggle.
    if (viewer?.documentId === documentId) {
      opener.current = null;
      restoreFocus.current = !panelOpen;
      setViewer(null);
      setPanelDuringViewer(false);
    }
    try {
      await removeDoc(threadId, documentId);
    } catch (error) {
      if (!alive.current || turn.current !== forTurn || error instanceof SessionExpiredError) return;
      // The server kept the document, so it kept the limit too.
      setScope(scopeBefore);
      void showDocumentsUsed(threadId, forTurn);
    }
  }

  // Before the thread exists, removing the starting document only forgets it: no request, and the first question goes
  // library-wide. The removed row had focus and there's no Add documents yet, so focus goes to the composer.
  function dropStarting(document: DocumentResponse) {
    setStarting(null);
    // Removing the open document closes the pane, as for a conversation's documents; focus goes to the question box.
    if (viewer?.documentId === document.document_id) {
      opener.current = null;
      setViewer(null);
      setPanelDuringViewer(false);
    }
    forgetStartParam();
    setAnnouncement(`${document.title} removed from this conversation.`);
    input.current?.focus();
  }

  // A refusal rejects with the server's message, which the title field shows.
  async function renameTitle(newTitle: string) {
    if (threadId === null) return;
    const forTurn = turn.current;
    const saved = await rename(threadId, newTitle);
    conversations.refresh();
    if (alive.current && turn.current === forTurn) setRenamed(saved);
  }

  // Archive or restore the conversation (US-13). Only its status changes; the history stays where it is. A failure keeps
  // the status and says why; a SessionExpiredError was already reported by the API client.
  async function changeArchived(archiving: boolean, from: "panel" | "banner" = "panel") {
    if (threadId === null) return;
    const forTurn = turn.current;
    setChangingStatus(true);
    try {
      await (archiving ? archive : restore)(threadId);
      if (!alive.current || turn.current !== forTurn) return;
      setArchived(archiving);
      // Only this action's own failure is cleared; a failed question's problem stays.
      const own = statusProblem.current; // read now: the updater runs at the next render
      setProblem((p) => (p !== null && p.message === own ? null : p));
      statusProblem.current = null;
      setAnnouncement(archiving ? "Conversation archived." : "Conversation restored.");
      setFocusAfterStatus(archiving ? "action" : "composer");
    } catch (error) {
      if (!alive.current || turn.current !== forTurn || error instanceof SessionExpiredError) return;
      const message = `Couldn't ${archiving ? "archive" : "restore"} this conversation. Try again.`;
      statusProblem.current = message;
      setProblem({ message });
      setAnnouncement(message);
      // The clicked button was disabled while the request ran, so focus fell away; give it back once it is enabled.
      setFocusAfterStatus(from === "banner" && !archiving ? "banner" : "action");
    } finally {
      // Another conversation opened meanwhile has its own status to change.
      if (alive.current && turn.current === forTurn) setChangingStatus(false);
      // The side nav's recent list drops or regains it.
      conversations.refresh();
    }
  }

  // Saves the learner's rating of one turn and shows what the server kept. A failure rejects to the buttons, which say so.
  // Only the newest request for a turn may update it: replies can arrive out of order.
  async function rateTurn(runId: string, rating: Rating) {
    if (threadId === null) return;
    const forTurn = turn.current;
    const request = (rateRequests.current[runId] = (rateRequests.current[runId] ?? 0) + 1);
    const saved = await rate(threadId, runId, rating);
    if (alive.current && turn.current === forTurn && rateRequests.current[runId] === request) setTurns((list) => list.map((e) => (e.runId === runId ? { ...e, rating: saved } : e)));
  }

  // The button goes once the pane is at the bottom, so focus moves on: to the question box, or while it is disabled
  // during an answer, to the newest turn (so the next Tab continues from there, not from the first turn).
  function jumpToLatest() {
    scroll.toLatest();
    if (answering) scroll.element?.querySelector<HTMLElement>("[data-newest-turn]")?.focus({ preventScroll: true });
    else input.current?.focus();
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

  // A conversation opened from its URL shows its history even without ready documents; a question there gets the upload
  // request under it.
  if (noDocuments && routeThreadId === undefined) {
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

  // Unknown, another learner's, or not a conversation id: the server doesn't say which.
  if (opened.status === "not-found") {
    return (
      <div className={styles.fallback}>
        <div className={styles.column}>
          <EmptyState
            icon={MessageSquareX}
            title="Conversation not found"
            actions={
              <LinkButton to="/chat" variant="primary" icon={MessageSquare}>
                Back to Chat
              </LinkButton>
            }
          >
            This conversation doesn't exist, or it isn't yours.
          </EmptyState>
        </div>
      </div>
    );
  }

  if (opened.status === "failed") {
    return (
      <div className={styles.fallback}>
        <div className={styles.column}>
          <PageHeader title="Conversation" />
          <p className={styles.problem}>
            <CircleAlert className={styles.problemIcon} strokeWidth={1.5} aria-hidden="true" />
            This conversation couldn't be loaded. Reload the page to try again.
          </p>
        </div>
      </div>
    );
  }

  if (library.status !== "ready") {
    return (
      <div className={styles.fallback}>
        <div className={styles.column}>
          <PageHeader title={routeThreadId === undefined ? "New conversation" : "Conversation"} />
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
  // The title starts as the first question until the learner renames it (PRD §9.4). A conversation URL that is still
  // loading, or whose thread has no title, is not a new conversation.
  const title = renamed ?? firstQuestion ?? (routeThreadId === undefined ? "New conversation" : "Conversation");
  const showPanel = viewer ? panelDuringViewer : panelOpen;
  const toggleLabel = showPanel ? "Hide panel" : "Show panel";
  const onTogglePanel = viewer ? () => setPanelDuringViewer((open) => !open) : toggle;
  const bodyClass = [styles.body, showPanel && styles.withPanel, viewer && styles.withViewer].filter(Boolean).join(" ");

  return (
    <div ref={pageRef} className={styles.page}>
      {/* One 40px row: the panel toggle, the conversation's title, and New conversation (DESIGN.md → Chat). */}
      <header className={styles.header}>
        <button
          ref={toggleRef}
          type="button"
          className={styles.toggle}
          aria-label={toggleLabel}
          title={toggleLabel}
          aria-expanded={showPanel}
          aria-controls={PANEL_ID}
          onClick={onTogglePanel}
        >
          <PanelLeft className={styles.toggleIcon} strokeWidth={1.5} aria-hidden="true" />
        </button>
        {/* Editable once the server has started the conversation, until it is archived (US-13). */}
        <ThreadTitle title={title} editable={threadId !== null && !archived} onRename={renameTitle} />
        {/* Not on an empty /chat: that is already a new conversation. */}
        {(routeThreadId !== undefined || turns.length > 0) && (
          <Button size="sm" variant="quiet" icon={SquarePen} className={styles.newConversation} onClick={newConversation}>
            New conversation
          </Button>
        )}
      </header>

      <p role="status" className="visually-hidden">
        {announcement}
      </p>

      <div className={bodyClass}>
        {showPanel && (
          <ConversationPanel
            id={PANEL_ID}
            documents={pendingStart ? [asListed(pendingStart)] : used}
            documentsFailed={usedFailed}
            threadId={threadId}
            answered={answered}
            showCitations={showCitations}
            onShowCitationsChange={setShowCitations}
            onAddDocuments={() => setPickerOpen(true)}
            onRemoveDocument={
              pendingStart
                ? () => dropStarting(pendingStart)
                : threadId === null
                  ? undefined
                  : (documentId) => void removeDocument(threadId, documentId)
            }
            onOpen={openDocument}
            openId={viewer?.documentId ?? null}
            searchListed={scope === "listed"}
            onSearchListedChange={threadId === null ? undefined : (on) => void changeSearchScope(threadId, on)}
            archived={archived}
            onArchive={() => void changeArchived(true)}
            onRestore={() => void changeArchived(false)}
            actionsDisabled={answering || changingStatus}
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
          <div ref={scroll.ref} className={styles.messages} role="region" aria-label="Messages">
            <div className={styles.column}>
              {pendingStart && (
                <p className={styles.notice}>
                  <FileText className={styles.noticeIcon} strokeWidth={1.5} aria-hidden="true" />
                  <span>
                    Started from <em>{pendingStart.title}</em>. It's listed in Documents; answers still use all your documents.
                  </span>
                </p>
              )}
              {/* While a conversation from its URL loads, its history is on its way: no welcome. */}
              {turns.length === 0 && routeThreadId === undefined && (
                <section className={styles.welcome}>
                  <h2 className={styles.welcomeTitle}>Ask about your documents</h2>
                  <p className={styles.welcomeText}>
                    I answer only from the documents in your Library and show the page each answer came from. There's
                    nothing to choose first: just ask.
                  </p>
                </section>
              )}

              {turns.map((t, index) => {
                const last = index === turns.length - 1;
                // A turn that didn't end with done wasn't saved, so it can't be rated.
                const runId = t.kept ? t.runId : null;
                const rating = runId !== null && threadId !== null ? <AnswerRating rating={t.rating} onRate={(r) => rateTurn(runId, r)} onAnnounce={setAnnouncement} /> : null;
                // Answer shows the Sources line on the same condition, with the rating at its end.
                const hasSources = t.decline === null && showCitations && t.citations.length > 0;
                return (
                  // Turns are only ever added at the end or all replaced, so the index is a stable key.
                  <div key={index} className={styles.turn} {...(last ? { "data-newest-turn": "", tabIndex: -1 } : {})}>
                    <p className={styles.question}>
                      <span className="visually-hidden">You asked: </span>
                      {t.question}
                    </p>

                    {/* Only the last turn's answer is announced, once when it is complete, never word by word; the
                        history is not (DESIGN.md → Accessibility). */}
                    <div
                      className={styles.answerRegion}
                      aria-live={last ? "polite" : undefined}
                      aria-busy={last ? answering : undefined}
                    >
                      {t.decline?.code === "no_documents" ? (
                        <div className={styles.declineCard}>
                          <p>{t.decline.message}</p>
                          {/* The way out is for the latest question only, as for the limited decline. */}
                          {last && (
                            <>
                              <p className={styles.muted}>Upload a document to get an answer. Your earlier answers stay readable.</p>
                              <div className={styles.declineActions}>
                                <LinkButton to="/library" icon={Upload}>
                                  Upload
                                </LinkButton>
                              </div>
                            </>
                          )}
                        </div>
                      ) : t.decline?.code === "limited" ? (
                        <div className={styles.declineCard}>
                          <p>{t.decline.message}</p>
                          {/* The way out is for the latest question only; an earlier decline keeps just its message. */}
                          {last && (
                            <>
                              <p className={styles.muted}>This conversation only searches {documentCount(used.length)}.</p>
                              <div className={styles.declineActions}>
                                {/* Off in an archived conversation: its documents and scope can't change. */}
                                <Button icon={Plus} aria-haspopup="dialog" disabled={answering || archived} onClick={() => setPickerOpen(true)}>
                                  Add documents
                                </Button>
                                <Button
                                  icon={Search}
                                  disabled={answering || threadId === null || archived}
                                  onClick={() => threadId !== null && void searchAll(threadId, t.question)}
                                >
                                  Search all my documents
                                </Button>
                              </div>
                            </>
                          )}
                        </div>
                      ) : t.decline != null ? (
                        // A code this page has no way out for: the message alone.
                        <div className={styles.declineCard}>
                          <p>{t.decline.message}</p>
                        </div>
                      ) : (
                        <Answer
                          text={t.answer}
                          citations={t.citations}
                          showCitations={showCitations}
                          deletedIds={deletedIds}
                          shownChunkId={viewer?.turn === index ? (viewer.chunkId ?? null) : null}
                          onOpenCitation={(c, from) => openCitation(c, index, from)}
                          rating={rating}
                        />
                      )}
                      {!hasSources && rating && <div className={styles.ratingLine}>{rating}</div>}
                      {last && problem && (
                        <p className={styles.problem}>
                          <CircleAlert className={styles.problemIcon} strokeWidth={1.5} aria-hidden="true" />
                          {problem.message}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}

              {/* With no turn to show it under (e.g. an archive that failed), the problem stays above the composer. */}
              {turns.length === 0 && problem && (
                <p className={styles.problem}>
                  <CircleAlert className={styles.problemIcon} strokeWidth={1.5} aria-hidden="true" />
                  {problem.message}
                </p>
              )}

              {answering && <p className={styles.thinking}>The tutor is answering…</p>}
            </div>
          </div>

          <form className={styles.form} onSubmit={onSubmit}>
            {/* Floats above the composer while the learner reads earlier turns; not a live region. */}
            {scroll.away && turns.length > 0 && (
              <Button size="sm" icon={ArrowDown} className={styles.jump} onClick={jumpToLatest}>
                Jump to latest
              </Button>
            )}
            <label htmlFor="chat-question" className="visually-hidden">
              Your question
            </label>
            {scope === "listed" && (
              <p className={styles.scopeLine}>
                <Filter className={styles.scopeIcon} strokeWidth={1.5} aria-hidden="true" />
                {`Searching ${documentCount(used.length)} `}
                {/* An archived conversation's scope can't change. */}
                {!archived && (
                  <button type="button" className={styles.linkButton} onClick={changeScope}>
                    Change
                  </button>
                )}
              </p>
            )}
            {archived && (
              <div className={styles.archivedBanner}>
                <Banner
                  variant="neutral"
                  icon={Archive}
                  title="This conversation is archived."
                  action={
                    <Button variant="primary" size="sm" icon={ArchiveRestore} data-banner-restore disabled={changingStatus} onClick={() => void changeArchived(false, "banner")}>
                      Restore
                    </Button>
                  }
                >
                  Restore it to keep asking.
                </Banner>
              </div>
            )}
            <div className={`${styles.composer} ${archived ? styles.composerArchived : ""}`}>
              <textarea
                ref={input}
                id="chat-question"
                className={styles.input}
                rows={1}
                maxLength={MAX_QUESTION}
                placeholder={archived ? "Archived conversation" : "Ask about your documents"}
                value={question}
                disabled={answering || archived}
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

        {viewer && (
          <div className={styles.viewer}>
            <DocumentPane
              documentId={viewer.documentId}
              passage={viewer.passage}
              onClose={closeDocument}
              viewerDeps={viewerDeps}
            />
          </div>
        )}
      </div>
    </div>
  );
}
